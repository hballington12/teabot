"""Per-server command sync (D32).

The admin plugin's groups are global commands, so every server can always reach `/plugins`. Each installed
plugin's group is a guild command only in servers where it is enabled. A `sync_commands` job works out the
set a server should have when it runs, compares its hash with `core.command_sync`, and only when they
differ sends one bulk overwrite and then saves the hash. Running it twice, or after a crash, changes
nothing, and a refused overwrite saves nothing, so its retry sends again.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from teapot.adapters.schema import commands_for
from teapot.core.queue import JobContext, NewJob, Queue
from teapot.core.registry import ActionSource
from teapot.db.pool import Database

SYNC_HANDLER = "sync_commands"
# The hash row of the global set. Discord ids are never 0.
GLOBAL_ROW = 0

ENABLED_HERE = "SELECT plugin_id FROM core.guild_plugins WHERE guild_id = $1 AND enabled"
STORED = "SELECT hash FROM core.command_sync WHERE guild_id = $1"
SAVE = """
INSERT INTO core.command_sync (guild_id, hash) VALUES ($1, $2)
ON CONFLICT (guild_id) DO UPDATE SET hash = EXCLUDED.hash, synced_at = now()
"""
# Every server with plugin rows or a synced set, with the plugins enabled there and the stored hash.
EVERY_SERVER = """
SELECT g.guild_id,
       coalesce(array_agg(gp.plugin_id) FILTER (WHERE gp.enabled), '{}') AS enabled,
       s.hash
FROM (SELECT guild_id FROM core.guild_plugins
      UNION SELECT guild_id FROM core.command_sync WHERE guild_id <> 0) g
LEFT JOIN core.guild_plugins gp ON gp.guild_id = g.guild_id
LEFT JOIN core.command_sync s ON s.guild_id = g.guild_id
GROUP BY g.guild_id, s.hash
"""

type Commands = list[dict[str, Any]]


class CommandApi(Protocol):
    """Discord's bulk overwrite: the global commands when `guild_id` is None, else one server's."""

    async def overwrite_commands(self, guild_id: int | None, commands: Commands, /) -> None: ...


def digest(commands: Commands) -> str:
    return hashlib.sha256(json.dumps(commands, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# A server with no stored hash has never been given commands.
NEVER_SYNCED = digest([])


class CommandSync:
    def __init__(
        self, db: Database, queue: Queue, sources: Mapping[str, ActionSource], api: CommandApi
    ) -> None:
        self.db = db
        self.queue = queue
        self.api = api
        self.installed = {p: s for p, s in sorted(sources.items()) if not s.builtin}
        self.global_commands = commands_for({p: s for p, s in sorted(sources.items()) if s.builtin})

    def commands_here(self, enabled: Iterable[str]) -> Commands:
        """The groups of the loaded plugins in `enabled`, by plugin id. Unloaded plugins have none."""
        wanted = set(enabled)
        return commands_for({p: s for p, s in self.installed.items() if p in wanted})

    async def request(self, guild_id: int | None) -> None:
        """Queue a sync for one server, or for the global set when `guild_id` is None."""
        await self.queue.schedule(NewJob("core", SYNC_HANDLER, guild_id=guild_id))

    async def _wanted(self, guild_id: int | None) -> Commands:
        if guild_id is None:
            return self.global_commands
        return self.commands_here(r["plugin_id"] for r in await self.db.fetch(ENABLED_HERE, guild_id))

    async def __call__(self, ctx: JobContext) -> None:
        guild_id = ctx.job.guild_id
        commands = await self._wanted(guild_id)
        row = GLOBAL_ROW if guild_id is None else guild_id
        wanted = digest(commands)
        if (await self.db.fetchval(STORED, row) or NEVER_SYNCED) == wanted:
            return
        await self.api.overwrite_commands(guild_id, commands)
        await self.db.execute(SAVE, row, wanted)

    async def startup(self) -> int:
        """Queue a sync for the global set and each server whose set changed. Returns how many."""
        stale: list[int | None] = []
        if (await self.db.fetchval(STORED, GLOBAL_ROW) or NEVER_SYNCED) != digest(self.global_commands):
            stale.append(None)
        for row in await self.db.fetch(EVERY_SERVER):
            if (row["hash"] or NEVER_SYNCED) != digest(self.commands_here(row["enabled"])):
                stale.append(row["guild_id"])
        for guild_id in stale:
            await self.request(guild_id)
        return len(stale)
