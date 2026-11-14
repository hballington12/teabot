"""Plugin jobs on the core queue (D31): each runs with its server, payload, server-bound database and client."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from teabot.core.config import ConfigStore
from teabot.core.loader import Loaded
from teabot.core.queue import JobContext as CoreJobContext
from teabot.core.queue import Queue
from teabot.db.pool import GuildPluginDatabase, Pools
from teabot.sdk import JobHandler

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PluginJobContext:
    """The SDK's `JobContext` for one run of a plugin's job."""

    guild_id: int
    payload: Mapping[str, Any]
    db: GuildPluginDatabase
    client: Any
    core: CoreJobContext
    started_by: int | None = None
    config: Any = None

    async def report(self, progress: Mapping[str, Any]) -> None:
        await self.core.report(dict(progress))


def _adapt(plugin_id: str, handler: JobHandler, pools: Pools, client: Any, config: type[BaseModel]) -> Any:
    store = ConfigStore(pools.core_db())

    async def run(core: CoreJobContext) -> None:
        guild_id = core.job.guild_id
        if guild_id is None:
            raise ValueError(f"{plugin_id}.{core.job.handler}: a plugin's job belongs to a server")
        if client.get_guild(guild_id) is None:
            # The bot has left the server, so the job has nothing to act on; it ends without retrying.
            log.info(
                "job dropped: the bot is not in its server",
                extra={"job_id": core.job.id, "guild_id": guild_id},
            )
            return
        started_by = core.job.started_by
        db = pools.guild_plugin_db(plugin_id, guild_id, started_by)
        settings = await store.load(guild_id, plugin_id, config)
        await handler(PluginJobContext(guild_id, core.job.payload, db, client, core, started_by, settings))

    return run


def register_plugin_jobs(queue: Queue, loaded: Mapping[str, Loaded], pools: Pools, client: Any) -> None:
    for plugin_id, plugin in loaded.items():
        for name, handler in plugin.jobs.items():
            queue.register(
                plugin_id, name, _adapt(plugin_id, handler, pools, client, plugin.plugin.manifest.config)
            )
