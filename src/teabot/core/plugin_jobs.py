"""Plugin jobs on the core queue (D31): each runs with its server, payload, server-bound database and client."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from teabot.core.loader import Loaded
from teabot.core.queue import JobContext as CoreJobContext
from teabot.core.queue import Queue
from teabot.db.pool import GuildPluginDatabase, Pools
from teabot.sdk import JobHandler


@dataclass(frozen=True)
class PluginJobContext:
    """The SDK's `JobContext` for one run of a plugin's job."""

    guild_id: int
    payload: Mapping[str, Any]
    db: GuildPluginDatabase
    client: Any
    core: CoreJobContext

    async def report(self, progress: Mapping[str, Any]) -> None:
        await self.core.report(dict(progress))


def _adapt(plugin_id: str, handler: JobHandler, pools: Pools, client: Any) -> Any:
    async def run(core: CoreJobContext) -> None:
        guild_id = core.job.guild_id
        if guild_id is None:
            raise ValueError(f"{plugin_id}.{core.job.handler}: a plugin's job belongs to a server")
        db = pools.guild_plugin_db(plugin_id, guild_id)
        await handler(PluginJobContext(guild_id, core.job.payload, db, client, core))

    return run


def register_plugin_jobs(queue: Queue, loaded: Mapping[str, Loaded], pools: Pools, client: Any) -> None:
    for plugin_id, plugin in loaded.items():
        for name, handler in plugin.jobs.items():
            queue.register(plugin_id, name, _adapt(plugin_id, handler, pools, client))
