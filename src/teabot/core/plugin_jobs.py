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
from teabot.core.recurring import Recurring
from teabot.db.pool import GuildPluginDatabase, Pools
from teabot.sdk import JobHandler
from teabot.sdk.actions import JOB_TIMEOUT

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


@dataclass(frozen=True)
class _Runtime:
    """What every plugin job runs with: the pools, the Discord client, and the recurring jobs."""

    pools: Pools
    client: Any
    recurring: Recurring | None = None


def _adapt(
    plugin_id: str, handler: JobHandler, runtime: _Runtime, config: type[BaseModel], recurs: bool
) -> Any:
    pools, client, recurring = runtime.pools, runtime.client, runtime.recurring if recurs else None
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
        if recurring is not None:
            await recurring.next_run(guild_id, plugin_id, core.job.handler, core.job.id)
        started_by = core.job.started_by
        db = pools.guild_plugin_db(plugin_id, guild_id, started_by)
        settings = await store.load(guild_id, plugin_id, config)
        await handler(PluginJobContext(guild_id, core.job.payload, db, client, core, started_by, settings))

    return run


def register_plugin_jobs(
    queue: Queue, loaded: Mapping[str, Loaded], pools: Pools, client: Any, recurring: Recurring | None = None
) -> None:
    """Register every loaded plugin's jobs. A recurring one queues its next run as it starts."""
    for plugin_id, plugin in loaded.items():
        config = plugin.plugin.manifest.config
        runtime = _Runtime(pools, client, recurring)
        for name, handler in plugin.jobs.items():
            adapted = _adapt(plugin_id, handler, runtime, config, name in plugin.recurring)
            queue.register(plugin_id, name, adapted, plugin.timeouts.get(name, JOB_TIMEOUT))
