"""The directory's reconcile (D55): Discord's documented member list, paged through the shard's writer.

Discord lists members in user ID order, so each page covers a known range of IDs, which the writer compares when it
reaches the page, after every event received before it. The cursor is the job's progress, so a crash resumes at the
next page. A server's first reconcile is its backfill, which writes rows and no history and tells plugins nothing.

The guard: in a server above `GUARD_FLOOR` members, a listing that ends well short of Discord's own member count was
cut off, so its last page marks no one as left, and the server's state says the run stopped short.
"""

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from teabot.core.directory import state as states
from teabot.core.directory.inbox import Entry, Page, RoleDeleted
from teabot.core.directory.joins import Search, read_joins
from teabot.core.directory.rows import MemberRow
from teabot.core.queue import NOTIFY_CHANNEL, JobContext, Queue
from teabot.db.pool import Database

log = logging.getLogger(__name__)

RECONCILE = "directory_reconcile"
KEY = "directory:reconcile"
PAGE = 1000
GUARD_FLOOR = 300
GUARD_SHARE = 0.9
MARGIN = timedelta(minutes=1)
# A daily run is skipped when the server was reconciled more recently, such as after a deploy.
RECENT = timedelta(hours=23)
DAY_SECONDS = 86_400
# Reconciles running at once in a process, so a deploy's burst leaves the other workers to plugins' jobs. Another
# waits its turn as a pending job.
AT_ONCE = 2
WAIT_TURN = timedelta(seconds=30)

# One pending reconcile per server. A second request keeps the earlier time and the earlier start of the gap, and
# a daily run asked for again for another reason runs for that reason.
REQUEST = f"""
INSERT INTO core.jobs (guild_id, plugin_id, handler, run_at, payload, key)
VALUES ($1, 'core', '{RECONCILE}', now() + $2::interval, $3::jsonb, '{KEY}')
ON CONFLICT (plugin_id, guild_id, key) WHERE state = 'pending' AND key IS NOT NULL DO UPDATE SET
    run_at = least(core.jobs.run_at, EXCLUDED.run_at),
    payload = jsonb_build_object(
        'reason', CASE WHEN core.jobs.payload->>'reason' = 'daily' THEN EXCLUDED.payload->>'reason'
                       ELSE core.jobs.payload->>'reason' END,
        'since', (SELECT min(s) FROM (VALUES (core.jobs.payload->>'since'), (EXCLUDED.payload->>'since')) AS v(s)))
RETURNING id
"""
PROGRESS = "SELECT progress FROM core.jobs WHERE id = $1"
HELD_ROLES = (
    "SELECT DISTINCT unnest(role_ids) AS role_id FROM core.members WHERE guild_id = $1 AND left_at IS NULL"
)
ACTIVE = "SELECT guild_id FROM core.guilds WHERE removed_at IS NULL ORDER BY guild_id"


class GuildFacts(Protocol):
    @property
    def member_count(self) -> int | None: ...

    @property
    def role_ids(self) -> frozenset[int]: ...


class MemberApi(Search, Protocol):
    """What the directory asks Discord, and knows of the client: its shard count and its own user ID, once logged
    in."""

    def shard_count(self) -> int: ...

    def bot_id(self) -> int | None: ...

    def facts(self, guild_id: int, /) -> GuildFacts | None: ...

    async def list_members(self, guild_id: int, after: int, /) -> list[Mapping[str, Any]]: ...


class Sink(Protocol):
    """Where a reconcile's pages go: the shard's writer."""

    async def submit(self, page: Page, /) -> None: ...

    async def put(self, entry: Entry, /) -> None: ...

    def off_changed(self, guild_id: int, off: bool, /) -> None: ...


@dataclass(frozen=True)
class DirectorySettings:
    """The operator's choices (D55): how long history and members who left are kept, the member-count ceiling above
    which a server has no directory, and whether join methods are read from Discord's member search."""

    retention_days: int = 365
    member_limit: int | None = None
    join_lookup: bool = True


class Reconciler:
    """Queues reconciles and runs them."""

    def __init__(
        self, db: Database, queue: Queue, api: MemberApi, sink: Sink, settings: DirectorySettings
    ) -> None:
        self.db = db
        self.queue = queue
        self.api = api
        self.sink = sink
        self.settings = settings
        self.running = 0

    async def request(
        self, guild_id: int, reason: str, *, since: datetime | None = None, delay: timedelta = timedelta(0)
    ) -> None:
        """Queue a reconcile of one server, unless one is pending, which then keeps the earlier of the two."""
        payload = {"reason": reason, "since": since.isoformat() if since else None}
        job_id = await self.db.fetchval(REQUEST, guild_id, delay, json.dumps(payload))
        await self.db.execute("SELECT pg_notify($1, $2)", NOTIFY_CHANNEL, str(job_id))
        self.queue.wake()

    async def request_many(self, guild_ids: list[int], reason: str, *, spacing: timedelta) -> None:
        """Queue reconciles of many servers, `spacing` apart, so a shard's fresh session does not burst."""
        for i, guild_id in enumerate(guild_ids):
            await self.request(guild_id, reason, delay=spacing * i)

    async def daily(self, _today: Any = None) -> None:
        """Queue every server's daily reconcile, each at its own time of day, from its ID."""
        for row in await self.db.fetch(ACTIVE):
            guild_id = row["guild_id"]
            await self.request(guild_id, "daily", delay=timedelta(seconds=(guild_id >> 22) % DAY_SECONDS))

    async def __call__(self, ctx: JobContext) -> None:
        guild_id = ctx.job.guild_id
        if guild_id is not None and self.running >= AT_ONCE:
            since = ctx.job.payload.get("since")
            await self.request(
                guild_id,
                str(ctx.job.payload.get("reason", "daily")),
                since=datetime.fromisoformat(since) if since else None,
                delay=WAIT_TURN,
            )
            return
        self.running += 1
        try:
            await self._run(ctx)
        finally:
            self.running -= 1

    async def _run(self, ctx: JobContext) -> None:
        guild_id = ctx.job.guild_id
        facts = self.api.facts(guild_id) if guild_id is not None else None
        if guild_id is None or facts is None:
            return
        await self.db.execute(states.ENSURE, guild_id)
        state = await states.load(self.db, guild_id)
        now = datetime.now(UTC)
        reason = str(ctx.job.payload.get("reason", "daily"))
        if reason == "daily" and state.reconciled_at is not None and now - state.reconciled_at < RECENT:
            return
        if await self._ceiling(guild_id, facts, state):
            return
        state = await states.load(self.db, guild_id)
        since_text = ctx.job.payload.get("since")
        since = datetime.fromisoformat(since_text) if since_text else (state.reconciled_at or now)
        complete = await self._pages(ctx, guild_id, facts, since, backfill=not state.backfilled)
        await self._deleted_roles(guild_id, facts)
        await self.db.execute(states.RECONCILED, guild_id, datetime.now(UTC), complete)
        if self.settings.join_lookup:
            await self._joins(guild_id, state.joins_read_to if state.backfilled else None)

    async def _ceiling(self, guild_id: int, facts: GuildFacts, state: states.State) -> bool:
        """Turn the directory off above the ceiling, keeping its rows as they were, and on again below it, which
        backfills the server again. Returns whether it is off."""
        over = (
            self.settings.member_limit is not None and (facts.member_count or 0) > self.settings.member_limit
        )
        if over != state.off:
            await self.db.execute(states.SET_OFF, guild_id, over)
            self.sink.off_changed(guild_id, over)
            log.info("directory turned " + ("off" if over else "on"), extra={"guild_id": guild_id})
        return over

    async def _pages(
        self, ctx: JobContext, guild_id: int, facts: GuildFacts, since: datetime, *, backfill: bool
    ) -> bool:
        """Page the whole member list through the writer. Returns False when the guard stopped it short."""
        progress = await self.db.fetchval(PROGRESS, ctx.job.id)
        cursor: dict[str, Any] = json.loads(progress) if progress else {}
        after, seen = int(cursor.get("after", 0)), int(cursor.get("seen", 0))
        while True:
            started = datetime.now(UTC)
            listed = sorted(
                (MemberRow.from_payload(m) for m in await self.api.list_members(guild_id, after)),
                key=lambda m: m.user_id,
            )
            seen += len(listed)
            last = len(listed) < PAGE
            complete = not (last and _cut_off(seen, facts.member_count))
            if not complete:
                log.warning(
                    "directory reconcile stopped short",
                    extra={"guild_id": guild_id, "listed": seen, "member_count": facts.member_count},
                )
            page = Page(
                guild_id,
                listed,
                after,
                None if last else listed[-1].user_id,
                started - MARGIN,
                since,
                backfill,
                mark_left=complete,
            )
            await self.sink.submit(page)
            if last:
                return complete
            after = listed[-1].user_id
            await ctx.report({"after": after, "seen": seen})

    async def _deleted_roles(self, guild_id: int, facts: GuildFacts) -> None:
        """A role members' rows hold that the server no longer has was deleted while the bot was not watching."""
        held = {r["role_id"] for r in await self.db.fetch(HELD_ROLES, guild_id)}
        for role_id in sorted(held - facts.role_ids):
            await self.sink.put(RoleDeleted(guild_id, role_id, None, datetime.now(UTC)))

    async def joins_now(self, guild_id: int) -> None:
        """Read join methods newer than the last lookup, before a filter by join method (D55)."""
        if not self.settings.join_lookup:
            return
        state = await states.load(self.db, guild_id)
        if state.backfilled:
            await self._joins(guild_id, state.joins_read_to)

    async def _joins(self, guild_id: int, read_to: datetime | None) -> None:
        try:
            newest = await read_joins(self.api, self.db, guild_id, read_to)
        except Exception:
            log.warning(
                "member search failed; join methods stay unknown", extra={"guild_id": guild_id}, exc_info=True
            )
            return
        if newest is not None:
            await self.db.execute(states.JOINS_READ, guild_id, newest)


def _cut_off(seen: int, member_count: int | None) -> bool:
    return member_count is not None and member_count > GUARD_FLOOR and seen < member_count * GUARD_SHARE
