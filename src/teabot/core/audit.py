"""The audit log (D24).

- A change gets a `started` row before it runs; its outcome and its `post_audit` job are written in one
  transaction, so a post is never lost and never sent for a change that was not recorded.
- A lookup gets one row in `core.audit_reads`, whatever its outcome, and is never posted. A refused change
  gets one row in `core.audit_log` and is posted.
- `post_audit` posts to the server's log channel from the admin plugin's config, one line per entry naming its
  audit row. A run of entries by one member for one action is gathered into one post, and the post's row lists
  its entries, so a repeat after a crash adds nothing.
- Retention: read partitions are created ahead and dropped whole; old changes are trimmed in batches.
"""

import json
import logging
from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any, Protocol, cast

import discord

from teabot.builtin.config import AdminConfig
from teabot.core.config import ConfigStore
from teabot.core.queue import JobContext, NewJob, Queue
from teabot.core.registry import CallRecord
from teabot.db.pool import Database
from teabot.db.types import Record
from teabot.sdk import Risk
from teabot.sdk.inputs import InputKind

log = logging.getLogger(__name__)

POST_HANDLER = "post_audit"
# With back-off capped at an hour, 48 attempts span more than a day: an outage, or a log channel the bot cannot
# see until an admin fixes its permissions, delays a post without losing it (D24).
POST_ATTEMPTS = 48
# A change the operator made from the CLI has no Discord member, and one that spans the instance no server.
# Discord ids are never 0.
OPERATOR = 0
INSTANCE = 0

INSERT_CHANGE = """
INSERT INTO core.audit_log (guild_id, user_id, token_id, surface, action, input, risk, outcome, error)
VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9) RETURNING id
"""
INSERT_READ = """
INSERT INTO core.audit_reads (guild_id, user_id, token_id, surface, action, input, outcome, error)
VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
"""
FINISH = "UPDATE core.audit_log SET outcome = $2, error = $3 WHERE id = $1 RETURNING guild_id"


def _who(call: CallRecord) -> tuple[int, int, str | None, str, str, str]:
    actor = call.actor
    return call.guild_id, actor.user_id, actor.token_id, actor.via, call.action, json.dumps(dict(call.input))


class AuditLog:
    """The registry's `Audit`, over the core database."""

    def __init__(self, queue: Queue) -> None:
        self.queue = queue
        self.db = queue.db

    async def started(self, call: CallRecord) -> int:
        audit_id: int = await self.db.fetchval(INSERT_CHANGE, *_who(call), int(call.risk), "started", None)
        return audit_id

    async def finished(self, audit_id: int, outcome: str, error: str | None) -> None:
        async with self.db.transaction() as tx:
            guild_id: int = await tx.fetchval(FINISH, audit_id, outcome, error)
            await self._queue_post(tx, guild_id, audit_id)

    async def single(self, call: CallRecord, outcome: str, error: str | None) -> None:
        if call.risk is Risk.READ:
            await self.db.execute(INSERT_READ, *_who(call), outcome, error)
            return
        async with self.db.transaction() as tx:
            audit_id: int = await tx.fetchval(INSERT_CHANGE, *_who(call), int(call.risk), outcome, error)
            await self._queue_post(tx, call.guild_id, audit_id)

    async def operator_change(
        self, tx: Any, guild_id: int | None, action: str, details: dict[str, Any]
    ) -> int:
        """Record a change the operator made from the CLI, inside `tx`: for one server, whose log channel is
        told, or for the instance when `guild_id` is None."""
        audit_id: int = await tx.fetchval(
            INSERT_CHANGE,
            INSTANCE if guild_id is None else guild_id,
            OPERATOR,
            None,
            "cli",
            action,
            json.dumps(details),
            int(Risk.DESTRUCTIVE),
            "ok",
            None,
        )
        if guild_id is not None:
            await self._queue_post(tx, guild_id, audit_id)
        return audit_id

    async def post(self, tx: Any, guild_id: int, audit_id: int) -> None:
        """Queue a row's post to the server's log channel, inside `tx`."""
        await self._queue_post(tx, guild_id, audit_id)

    async def _queue_post(self, tx: Any, guild_id: int, audit_id: int) -> None:
        job = NewJob(
            "core",
            POST_HANDLER,
            guild_id=guild_id,
            payload={"audit_id": audit_id},
            max_attempts=POST_ATTEMPTS,
        )
        await self.queue.schedule(job, within=tx)


class Message(Protocol):
    async def edit(self, *, content: str, allowed_mentions: discord.AllowedMentions) -> Any: ...


class Channel(Protocol):
    async def send(self, content: str, *, allowed_mentions: discord.AllowedMentions) -> Any: ...

    def get_partial_message(self, message_id: int, /) -> Message: ...


class ChannelSource(Protocol):
    def get_channel(self, channel_id: int, /) -> Any: ...


type Kinds = Mapping[str, Mapping[str, InputKind]]
"""Each action's input fields and their kinds, so a post shows members, roles and channels as mentions."""

OUTCOMES = {"ok": "🟢", "refused": "🟠", "error": "🔴", "handed_off": "🔵"}
# Entries by one member for one action, through one front door, this close together, share a post.
GATHER_WITHIN = timedelta(minutes=2)
GATHER_MOST = 10
POST_MAX = 1900
VALUE_SHOWN = 80
ERROR_SHOWN = 300
# A plan's confirm value says nothing a reader needs.
HIDDEN = frozenset({"confirm"})
MENTIONS = {"member": "<@{}>", "role": "<@&{}>", "channel": "<#{}>", "voice_channel": "<#{}>"}


def _shown(value: Any, kind: InputKind | None) -> str:
    if isinstance(value, list):
        return ", ".join(_shown(v, kind) for v in cast(list[Any], value))
    if kind in MENTIONS and str(value).isdigit():
        return MENTIONS[kind].format(value)
    if isinstance(value, str):
        text = value.replace("`", "'").replace("\n", " ")
        return f"`{text[:VALUE_SHOWN]}{'…' if len(text) > VALUE_SHOWN else ''}`"
    return str(value)


def audit_header(row: Record) -> str:
    """The first line of a post: the action, who ran it, and how it came in."""
    member = "the operator" if row["user_id"] == OPERATOR else f"<@{row['user_id']}>"
    return f"**{row['action']}** · {member} · {row['surface']}"


def audit_line(row: Record, kinds: Kinds) -> str:
    """One entry's line: its outcome, what was asked for, any error, and its audit number."""
    fields = kinds.get(row["action"], {})
    given: dict[str, Any] = json.loads(row["input"]) if row["input"] else {}
    parts = [
        f"{name}: {_shown(value, fields.get(name))}"
        for name, value in given.items()
        if name not in HIDDEN and value not in (None, "", [])
    ]
    if row["error"]:
        error = str(row["error"]).replace("\n", " ")
        parts.append(f"error: {error[:ERROR_SHOWN]}")
    return f"{OUTCOMES.get(row['outcome'], '⚪')} " + " · ".join([*parts, f"#{row['id']}"])


def _content(header: str, lines: list[str]) -> str:
    return "\n".join([header, *lines])


NO_MENTIONS = discord.AllowedMentions.none()
LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('audit_posts:' || $1::bigint::text, 0))"
LAST = "SELECT * FROM core.audit_posts WHERE guild_id = $1"
SAVE = """
INSERT INTO core.audit_posts (guild_id, channel_id, message_id, audit_ids, lines, posted_at)
VALUES ($1, $2, $3, $4, $5, $6)
ON CONFLICT (guild_id) DO UPDATE SET channel_id = $2, message_id = $3, audit_ids = $4, lines = $5, posted_at = $6
"""


class PostAudit:
    """The `core.post_audit` handler. A run of entries by one member for one action, through one front door, a
    couple of minutes apart at most, is gathered into one post, a line each, by editing it."""

    def __init__(self, db: Database, client: ChannelSource, kinds: Kinds | None = None) -> None:
        self.db = db
        self.config = ConfigStore(db)
        self.client = client
        self.kinds: Kinds = kinds or {}

    async def __call__(self, ctx: JobContext) -> None:
        row = await self.db.fetchrow(
            "SELECT * FROM core.audit_log WHERE id = $1", ctx.job.payload["audit_id"]
        )
        if row is None:
            return
        config = await self.config.load(row["guild_id"], "admin", AdminConfig)
        channel = self.client.get_channel(config.log_channel_id) if config.log_channel_id else None
        if channel is None:
            return
        line = audit_line(row, self.kinds)
        async with self.db.transaction() as tx:
            await tx.execute(LOCK, row["guild_id"])
            last = await tx.fetchrow(LAST, row["guild_id"])
            if last is not None and row["id"] in last["audit_ids"]:
                return
            if last is not None and await self._joins(
                tx, last, row, channel_id=config.log_channel_id, line=line
            ):
                lines = [*last["lines"], line]
                try:
                    message = channel.get_partial_message(last["message_id"])
                    await message.edit(
                        content=_content(audit_header(row), lines), allowed_mentions=NO_MENTIONS
                    )
                except discord.NotFound:
                    pass
                else:
                    await tx.execute(
                        SAVE,
                        row["guild_id"],
                        last["channel_id"],
                        last["message_id"],
                        [*last["audit_ids"], row["id"]],
                        lines,
                        row["time"],
                    )
                    return
            sent = await channel.send(_content(audit_header(row), [line]), allowed_mentions=NO_MENTIONS)
            await tx.execute(
                SAVE, row["guild_id"], config.log_channel_id, sent.id, [row["id"]], [line], row["time"]
            )

    async def _joins(self, tx: Any, last: Record, row: Record, *, channel_id: int | None, line: str) -> bool:
        """Whether `row` joins the server's latest post: same channel, member, action and front door, soon after,
        with room left."""
        if last["channel_id"] != channel_id or len(last["lines"]) >= GATHER_MOST:
            return False
        if row["time"] - last["posted_at"] > GATHER_WITHIN:
            return False
        if len(_content(audit_header(row), [*last["lines"], line])) > POST_MAX:
            return False
        previous = await tx.fetchrow(
            "SELECT action, user_id, surface FROM core.audit_log WHERE id = $1", last["audit_ids"][-1]
        )
        return previous is not None and (previous["action"], previous["user_id"], previous["surface"]) == (
            row["action"],
            row["user_id"],
            row["surface"],
        )


async def ensure_read_partitions(db: Database, start: date, *, days_ahead: int) -> None:
    await db.execute("SELECT core.ensure_audit_read_partitions($1, $2)", start, days_ahead)


class AuditMaintenance:
    """Retention for the audit tables, run from the daily maintenance job (D24)."""

    def __init__(
        self, db: Database, *, reads_days: int = 30, changes_days: int = 365, batch: int = 5000
    ) -> None:
        self.db = db
        self.reads_days = reads_days
        self.changes_days = changes_days
        self.batch = batch

    async def run(self, today: date) -> None:
        await ensure_read_partitions(self.db, today, days_ahead=7)
        await self.db.execute(
            "SELECT core.drop_audit_read_partitions($1)", today - timedelta(days=self.reads_days)
        )
        await self._trim(
            "DELETE FROM core.audit_log WHERE id IN (SELECT id FROM core.audit_log "
            "WHERE time < now() - make_interval(days => $1) LIMIT $2)",
            self.changes_days,
        )
        await self._trim(
            "DELETE FROM core.audit_reads_default WHERE ctid IN (SELECT ctid FROM core.audit_reads_default "
            "WHERE time < now() - make_interval(days => $1) LIMIT $2)",
            self.reads_days,
        )

    async def _trim(self, statement: str, days: int) -> None:
        while await self.db.execute(statement, days, self.batch) != "DELETE 0":
            pass
