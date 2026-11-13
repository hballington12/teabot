"""The audit log (D24).

- A change gets a `started` row before it runs; its outcome and its `post_audit` job are written in one
  transaction, so a post is never lost and never sent for a change that was not recorded.
- A lookup gets one row in `core.audit_reads`, whatever its outcome, and is never posted. A refused change
  gets one row in `core.audit_log` and is posted.
- `post_audit` posts to the server's log channel from the admin plugin's config, naming the audit row, so a
  repeat after a crash is recognisable.
- Retention: read partitions are created ahead and dropped whole; old changes are trimmed in batches.
"""

import json
import logging
from datetime import date, timedelta
from typing import Any, Protocol

import discord

from teapot.builtin.config import AdminConfig
from teapot.core.config import ConfigStore
from teapot.core.queue import JobContext, NewJob, Queue
from teapot.core.registry import CallRecord
from teapot.db.pool import Database
from teapot.db.types import Record
from teapot.sdk import Risk

log = logging.getLogger(__name__)

POST_HANDLER = "post_audit"
INPUT_SHOWN = 1000

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

    async def _queue_post(self, tx: Any, guild_id: int, audit_id: int) -> None:
        job = NewJob("core", POST_HANDLER, guild_id=guild_id, payload={"audit_id": audit_id})
        await self.queue.schedule(job, within=tx)


class Channel(Protocol):
    async def send(self, *, embed: discord.Embed) -> Any: ...


class ChannelSource(Protocol):
    def get_channel(self, channel_id: int, /) -> Any: ...


COLOURS = {"ok": discord.Colour.green(), "refused": discord.Colour.orange(), "error": discord.Colour.red()}


def audit_embed(row: Record) -> discord.Embed:
    """What a log channel shows for one audit row."""
    embed = discord.Embed(
        title=row["action"], colour=COLOURS.get(row["outcome"], discord.Colour.light_grey())
    )
    embed.add_field(name="Member", value=f"<@{row['user_id']}>")
    embed.add_field(name="Outcome", value=row["outcome"])
    embed.add_field(name="Front door", value=row["surface"])
    embed.add_field(name="Input", value=f"```{row['input'][:INPUT_SHOWN]}```", inline=False)
    if row["error"]:
        embed.add_field(name="Error", value=row["error"][:INPUT_SHOWN], inline=False)
    embed.set_footer(text=f"audit #{row['id']}")
    embed.timestamp = row["time"]
    return embed


class PostAudit:
    """The `core.post_audit` handler."""

    def __init__(self, db: Database, client: ChannelSource) -> None:
        self.db = db
        self.config = ConfigStore(db)
        self.client = client

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
        await channel.send(embed=audit_embed(row))


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
