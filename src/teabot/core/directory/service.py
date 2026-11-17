"""The member directory in a bot process (D55): a writer for each of its shards, the gateway's way in, the reconcile
and the daily upkeep, wired together."""

import logging
from collections.abc import Callable, MutableMapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from teabot.core.directory import state as states
from teabot.core.directory.apply import Apply
from teabot.core.directory.gateway import GuildLookup, install
from teabot.core.directory.inbox import Entry, Page
from teabot.core.directory.reconcile import RECONCILE, DirectorySettings, MemberApi, Reconciler
from teabot.core.directory.writer import Writer
from teabot.core.events import Events
from teabot.core.queue import Queue
from teabot.db.pool import Database

log = logging.getLogger(__name__)

RECONCILE_TIMEOUT = timedelta(hours=2)
# Reconciles a shard's fresh session asks for, this far apart.
SPACING = timedelta(seconds=2)
OFF = "SELECT guild_id FROM core.directory_state WHERE off"
# Members who left longer ago than the retention period, a batch at a time.
FORGET_LEFT = """
DELETE FROM core.members WHERE ctid IN (
    SELECT ctid FROM core.members WHERE left_at < now() - make_interval(days => $1) LIMIT $2)
"""
TRIM_DEFAULT = """
DELETE FROM core.member_events_default WHERE ctid IN (
    SELECT ctid FROM core.member_events_default WHERE at < now() - make_interval(days => $1) LIMIT $2)
"""


class Directory:
    """The directory's parts in one process. The client's shard count and user ID are read from `api` when needed,
    since the client knows them only once it has logged in."""

    def __init__(
        self, db: Database, queue: Queue, events: Events, api: MemberApi, settings: DirectorySettings
    ) -> None:
        self.db = db
        self.events = events
        self.api = api
        self.settings = settings
        self.off: set[int] = set()
        self.writers: dict[int, Writer] = {}
        self.listening = False
        self.reconciler = Reconciler(db, queue, api, self, settings)
        queue.register("core", RECONCILE, self.reconciler, RECONCILE_TIMEOUT)

    def shard_of(self, guild_id: int) -> int:
        return (guild_id >> 22) % max(self.api.shard_count(), 1)

    def writer(self, shard_id: int) -> Writer:
        found = self.writers.get(shard_id)
        if found is None:
            apply = Apply(self.events, self.off, self.api.bot_id)
            found = self.writers[shard_id] = Writer(shard_id, self.db, apply, on_dropped=self._dropped)
            found.start()
        return found

    def offer(self, entry: Entry) -> None:
        self.writer(self.shard_of(entry.guild_id)).offer(entry)

    async def put(self, entry: Entry) -> None:
        await self.writer(self.shard_of(entry.guild_id)).put(entry)

    async def submit(self, page: Page) -> None:
        await self.writer(self.shard_of(page.guild_id)).submit(page)

    def listen(self, parsers: MutableMapping[str, Callable[[Any], Any]], guild_of: GuildLookup) -> bool:
        """Wrap discord.py's member parsers. Returns whether the directory now hears member events."""
        self.listening = install(parsers, self.offer, guild_of)
        return self.listening

    async def start(self) -> None:
        self.off.update(r["guild_id"] for r in await self.db.fetch(OFF))

    async def close(self) -> None:
        for writer in list(self.writers.values()):
            await writer.close()

    def off_changed(self, guild_id: int, off: bool) -> None:
        if off:
            self.off.add(guild_id)
        else:
            self.off.discard(guild_id)

    async def _dropped(self, shard_id: int) -> None:
        """Events were dropped on a shard whose writer commits again: reconcile its servers."""
        guilds = [g for g in await self._active() if self.shard_of(g) == shard_id]
        await self.db.execute(states.MARK_DROPPED, guilds)
        await self.reconciler.request_many(guilds, "dropped", spacing=SPACING)

    async def _active(self) -> list[int]:
        return [
            r["guild_id"]
            for r in await self.db.fetch("SELECT guild_id FROM core.guilds WHERE removed_at IS NULL")
        ]

    async def fresh_session(self, guild_ids: list[int]) -> None:
        """A shard started a new session rather than resuming, so events were lost while it was away."""
        await self.reconciler.request_many(guild_ids, "session", spacing=SPACING)

    async def upkeep(self, today: date) -> None:
        """The daily maintenance (D31): next months' partitions, retention, and every server's daily reconcile."""
        days, batch = self.settings.retention_days, 5000
        await self.db.execute("SELECT core.ensure_member_event_partitions($1, 2)", today)
        await self.db.execute("SELECT core.drop_member_event_partitions($1)", today - timedelta(days=days))
        for statement in (FORGET_LEFT, TRIM_DEFAULT):
            while await self.db.execute(statement, days, batch) != "DELETE 0":
                pass
        await self.reconciler.daily()


async def ensure_partitions(db: Database) -> None:
    """This month's history partition and the next two, at startup, before any event is written."""
    await db.execute("SELECT core.ensure_member_event_partitions($1, 2)", datetime.now(UTC).date())
