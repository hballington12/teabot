"""Recurring plugin jobs (D31): `@plugin.job(every=...)` runs on its own in each server where the plugin is on.

Each server holds one pending run of each recurring job, keyed `every:<name>`, so scheduling it again changes
nothing. A run queues the next one before it starts, so a run that fails, even for good, never ends the chain.
teabot queues the first run one interval after it starts, and after a server turns the plugin on.
"""

from collections.abc import Mapping
from datetime import timedelta

from teabot.db.pool import Database

ONE_PENDING = """
INSERT INTO core.jobs (guild_id, plugin_id, handler, run_at, key)
VALUES ($1, $2, $3, now() + $4::interval, $5)
ON CONFLICT (plugin_id, guild_id, key) WHERE state = 'pending' AND key IS NOT NULL DO NOTHING
"""
# A run in progress gives up its key, so a retry after a failure, which makes it pending again, cannot collide
# with the next run.
RELEASE = "UPDATE core.jobs SET key = NULL WHERE id = $1"
ENABLED = "SELECT guild_id, plugin_id FROM core.guild_plugins WHERE enabled AND plugin_id = ANY($1::text[])"


def recurring_key(name: str) -> str:
    """The key of a recurring job's pending run."""
    return f"every:{name}"


class Recurring:
    """`jobs` maps each plugin to its recurring jobs and how often each runs."""

    def __init__(self, db: Database, jobs: Mapping[str, Mapping[str, timedelta]]) -> None:
        self.db = db
        self.jobs = {plugin_id: dict(found) for plugin_id, found in jobs.items() if found}

    async def next_run(self, guild_id: int, plugin_id: str, name: str, running: int | None = None) -> None:
        """Queue the next run of one recurring job in one server, unless one is pending already. `running` is
        the run starting now, which gives up its key first."""
        every = self.jobs[plugin_id][name]
        async with self.db.transaction() as tx:
            if running is not None:
                await tx.execute(RELEASE, running)
            await tx.execute(ONE_PENDING, guild_id, plugin_id, name, every, recurring_key(name))

    async def ensure(self, guild_id: int, plugin_id: str, _user_id: int = 0) -> None:
        """Queue every recurring job of the plugin in the server, such as when the server turns it on."""
        for name in self.jobs.get(plugin_id, {}):
            await self.next_run(guild_id, plugin_id, name)

    async def startup(self) -> int:
        """Queue the recurring jobs in every server where their plugin is on. Returns how many servers' plugins
        were checked."""
        rows = await self.db.fetch(ENABLED, list(self.jobs))
        for row in rows:
            await self.ensure(row["guild_id"], row["plugin_id"])
        return len(rows)
