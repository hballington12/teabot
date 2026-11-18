"""Plugin jobs on the core queue (D31): each runs with its server, payload, server-bound database and client."""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from teabot.core.config import ConfigStore
from teabot.core.directory.labels import GuildLabels, LabelService
from teabot.core.directory.plugin_api import GuildMembers
from teabot.core.grants import Grants
from teabot.core.loader import Loaded
from teabot.core.queue import JobContext as CoreJobContext
from teabot.core.queue import Queue
from teabot.core.recurring import Recurring
from teabot.core.voice import GuildVoice, VoiceService
from teabot.db.pool import GuildPluginDatabase, Pools
from teabot.sdk import Actor, JobHandler
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
    open_voice: GuildVoice | None = None
    members: GuildMembers | None = None
    grants: "BoundGrants | None" = None
    labels: GuildLabels | None = None

    def open_labels(self) -> GuildLabels:
        """The plugin's member labels, as `ctx.labels`; the SDK checks the plugin declared them."""
        if self.labels is None:
            raise RuntimeError("this job has no member labels")
        return self.labels

    def open_members(self) -> GuildMembers:
        """The server's member directory, as `ctx.members` (D55); the SDK checks the plugin declared it."""
        if self.members is None:
            raise RuntimeError("this job has no member directory")
        return self.members

    @property
    def voice(self) -> GuildVoice:
        if self.open_voice is None:
            raise RuntimeError("this job has no voice connection")
        return self.open_voice

    async def report(self, progress: Mapping[str, Any]) -> None:
        await self.core.report(dict(progress))


@dataclass(frozen=True)
class BoundGrants:
    """The core's grants, for one plugin's job in one server."""

    grants: Grants
    guild_id: int
    plugin_id: str

    async def authorized(self, audit_id: int) -> Actor:
        return await self.grants.authorized(self.guild_id, self.plugin_id, audit_id)

    async def record_outcome(self, audit_id: int, text: str, *, failed: bool = False) -> None:
        await self.grants.record_outcome(self.guild_id, audit_id, text, failed=failed)


@dataclass(frozen=True)
class _Runtime:
    """What every plugin job runs with: the pools, the Discord client, the recurring jobs and voice."""

    pools: Pools
    client: Any
    recurring: Recurring | None = None
    voice: VoiceService | None = None
    grants: Grants | None = None
    labels: LabelService | None = None


@dataclass(frozen=True)
class JobServices:
    """The core's services that plugin jobs use, besides the pools and the client."""

    recurring: Recurring | None = None
    voice: VoiceService | None = None
    grants: Grants | None = None
    labels: LabelService | None = None


def _adapt(
    plugin_id: str, handler: JobHandler, runtime: _Runtime, config: type[BaseModel], recurs: bool
) -> Any:
    pools, client, recurring = runtime.pools, runtime.client, runtime.recurring if recurs else None
    voice, grants, labels = runtime.voice, runtime.grants, runtime.labels
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
        bound = voice.bound(plugin_id, guild_id) if voice is not None else None
        await handler(
            PluginJobContext(
                guild_id,
                core.job.payload,
                db,
                client,
                core,
                started_by,
                settings,
                bound,
                GuildMembers(pools.core_db(), guild_id, labels),
                BoundGrants(grants, guild_id, plugin_id) if grants is not None else None,
                labels.bound(plugin_id, guild_id) if labels is not None else None,
            )
        )

    return run


def register_plugin_jobs(
    queue: Queue, loaded: Mapping[str, Loaded], pools: Pools, client: Any, services: JobServices | None = None
) -> None:
    """Register every loaded plugin's jobs. A recurring one queues its next run as it starts."""
    services = services or JobServices()
    for plugin_id, plugin in loaded.items():
        config = plugin.plugin.manifest.config
        runtime = _Runtime(
            pools, client, services.recurring, services.voice, services.grants, services.labels
        )
        for name, handler in plugin.jobs.items():
            adapted = _adapt(plugin_id, handler, runtime, config, name in plugin.recurring)
            queue.register(plugin_id, name, adapted, plugin.timeouts.get(name, JOB_TIMEOUT))
