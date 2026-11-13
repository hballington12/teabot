"""`teapot run`: the real parts of a bot process, wired for `teapot.runtime` (D27, D33, D40).

The core migrates first. The Discord client logs in, and in `setup_hook`, before any shard connects, fixes the
shard count and takes the shard locks. `teapot.runtime` supervises from there. This module only opens the
real parts; the orchestration is tested in `tests/test_runtime.py`, and this wiring in the live exit check.
"""

import asyncio
import contextlib
import logging
import math
import signal
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

import discord
import uvicorn

import teapot
from teapot.adapters.interactions import InteractionRouter, prune_drafts
from teapot.builtin.admin import Admin
from teapot.core.audit import POST_HANDLER, AuditLog, AuditMaintenance, PostAudit, ensure_read_partitions
from teapot.core.command_sync import SYNC_HANDLER, CommandSync
from teapot.core.config import ConfigStore
from teapot.core.lifecycle import PURGE_GUILD, Guilds
from teapot.core.loader import LoadReport, discover, load
from teapot.core.maintenance import Maintenance
from teapot.core.plugin_jobs import register_plugin_jobs
from teapot.core.processes import LockConnection, open_lock_connection
from teapot.core.queue import NOTIFY_CHANNEL, Queue, ShardFilter
from teapot.core.registry import Registry, sources_from
from teapot.core.worker import Workers
from teapot.db.migrate import MigrationReport, PluginMigrations, migrate
from teapot.db.naming import Naming
from teapot.db.pool import ConnectionInfo, Credentials, Login, Pools, Timing, connect, create_pools
from teapot.health import Health
from teapot.runtime import Runtime, serve_until_stopped
from teapot.settings import Settings
from teapot.web import build_app

log = logging.getLogger(__name__)

# teapot has no voice features, so discord.py's warnings about voice libraries are noise.
discord.VoiceClient.warn_nacl = False
discord.VoiceClient.warn_dave = False

SLOW_TRANSACTION_MS = 100.0


class Shard(Protocol):
    @property
    def latency(self) -> float: ...

    def is_closed(self) -> bool: ...


def shard_latencies(shards: Mapping[int, Shard]) -> dict[int, float | None]:
    """Gateway latency per shard, or None for a shard that is not connected."""
    return {
        shard_id: None if shard.is_closed() or not math.isfinite(shard.latency) else shard.latency
        for shard_id, shard in shards.items()
    }


def token_or_exit(token: str) -> str:
    if not token:
        raise SystemExit("TEAPOT_DISCORD_TOKEN is not set; put the bot token in teapot.env")
    return token


class TeapotClient(discord.AutoShardedClient):
    """The Discord client. Members are cached lazily (D25); interactions are routed by the core (D32)."""

    def __init__(self, lock: LockConnection) -> None:
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = False
        super().__init__(
            intents=intents,
            chunk_guilds_at_startup=False,
            member_cache_flags=discord.MemberCacheFlags.from_intents(intents),
        )
        self.lock = lock
        self.router: InteractionRouter | None = None
        self.lifecycle: Guilds | None = None
        self._shards: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def setup_hook(self) -> None:
        count, _url, _limits = await self.http.get_bot_gateway()
        self.shard_count = count
        self.shard_ids = list(range(count))
        await self.lock.take_shards(self.shard_ids)
        self._shards.set_result(count)
        log.info("shards locked", extra={"shard_count": count})

    async def overwrite_commands(self, guild_id: int | None, commands: list[dict[str, Any]], /) -> None:
        """One bulk overwrite (D32): the global commands when `guild_id` is None, else one server's.

        Sync jobs run only once the shards are locked, which is after login, so the application id is known.
        """
        if self.application_id is None:
            raise RuntimeError("not logged in to Discord yet")
        if guild_id is None:
            await self.http.bulk_upsert_global_commands(self.application_id, commands)
        else:
            await self.http.bulk_upsert_guild_commands(self.application_id, guild_id, commands)
        log.info("commands synced", extra={"guild_id": guild_id, "groups": len(commands)})

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if self.router is not None:
            await self.router.handle(interaction)

    async def on_guild_join(self, guild: discord.Guild) -> None:
        if self.lifecycle is not None:
            await self.lifecycle.joined(guild.id)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        if self.lifecycle is not None:
            await self.lifecycle.removed(guild.id)

    async def on_ready(self) -> None:
        """Find servers joined or left while the bot was down (D49). Ready can fire again after a
        reconnect; the comparison is safe to repeat. Unavailable servers are still in the cache, so an
        outage is never taken for a removal."""
        if self.lifecycle is None:
            return
        shards = ShardFilter(self.shard_count, tuple(self.shard_ids or range(self.shard_count)))
        joined, left = await self.lifecycle.reconcile([g.id for g in self.guilds], shards)
        log.info("servers reconciled", extra={"joined": joined, "left": left})

    async def wait_for_shards(self) -> int:
        return await asyncio.shield(self._shards)


class EmbeddedServer(uvicorn.Server):
    """uvicorn inside teapot's loop. teapot owns the signals, so uvicorn must not capture them."""

    def capture_signals(self) -> contextlib.AbstractContextManager[None]:  # pyright: ignore[reportIncompatibleMethodOverride]
        return contextlib.nullcontext()


async def _load_plugins(
    settings: Settings, info: ConnectionInfo, naming: Naming, lock: LockConnection
) -> LoadReport:
    """Migrate the core, then load the installed plugins under their locks (D9, D14, D15)."""
    conn = await connect(Login(info, settings.db_owner_user, settings.db_owner_password.get_secret_value()))

    async def migrator(plugins: Sequence[PluginMigrations]) -> MigrationReport:
        return await migrate(conn, naming, plugins)

    try:
        return await load(discover(), disabled=settings.disabled_plugins, migrate_with=migrator, lock=lock)
    finally:
        await conn.close()


async def _open_runtime(settings: Settings, token: str) -> Runtime:
    naming = Naming(settings.db_role_prefix)
    info = ConnectionInfo(settings.db_host, settings.db_port, settings.db_name)
    credentials = Credentials(
        settings.db_app_password.get_secret_value(), settings.db_plugins_password.get_secret_value()
    )
    timing = Timing(slow_ms=SLOW_TRANSACTION_MS if settings.dev_mode else None)
    pools: Pools = await create_pools(info, naming, credentials, size=settings.db_pool_size, timing=timing)
    stop, failed = asyncio.Event(), list[str]()

    def lock_lost() -> None:
        failed.append("lock connection lost")
        stop.set()

    lock = await open_lock_connection(Login(info, naming.app_role, credentials.app_password), lock_lost)
    report = await _load_plugins(settings, info, naming, lock)
    statuses = report.labels()
    queue = Queue(pools.core_db())

    async def prune(_today: date) -> None:
        await prune_drafts(pools.core_db())

    daily = [AuditMaintenance(pools.core_db()).run, prune]
    queue.register("core", "maintenance", Maintenance(queue, daily=daily))
    await ensure_read_partitions(pools.core_db(), datetime.now(UTC).date(), days_ahead=7)
    runnable = ["core", *report.loaded]
    workers = Workers(queue, lambda: runnable)
    await lock.conn.add_listener(NOTIFY_CHANNEL, workers.on_notify)
    configs = {p: loaded.plugin.manifest.config for p, loaded in report.loaded.items()}
    admin = Admin(pools.core_db(), statuses=statuses, configs=configs)
    sources = sources_from(report.loaded) | admin.sources()
    client = TeapotClient(lock)
    sync = CommandSync(pools.core_db(), queue, sources, client)
    admin.on_change = sync.request
    queue.register("core", SYNC_HANDLER, sync)
    client.lifecycle = Guilds(pools, queue, sync, timedelta(days=settings.guild_retention_days))
    queue.register("core", PURGE_GUILD, client.lifecycle.purge)
    log.info("command syncs queued", extra={"count": await sync.startup()})
    queue.register("core", POST_HANDLER, PostAudit(pools.core_db(), client))
    register_plugin_jobs(queue, report.loaded, pools, client)
    registry = Registry(
        sources,
        pools=pools,
        config=ConfigStore(pools.core_db()),
        client=client,
        audit=AuditLog(queue),
    )
    client.router = InteractionRouter(registry, pools.core_db())
    health = Health(
        teapot.__version__, pools.core_db(), lambda: shard_latencies(client.shards), lambda: statuses
    )
    config = uvicorn.Config(
        build_app(health), host=settings.http_host, port=settings.http_port, log_config=None, lifespan="off"
    )
    server = EmbeddedServer(config)
    return Runtime(
        token, teapot.__version__, pools, lock, workers, client, server, statuses, stop=stop, failed=failed
    )


async def main(settings: Settings) -> int:
    """Open the real parts, run until stopped, and return the exit code."""
    token = token_or_exit(settings.discord_token.get_secret_value())
    rt = await _open_runtime(settings, token)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, rt.stop.set)
    try:
        return await serve_until_stopped(rt)
    finally:
        await rt.pools.close()


def run(settings: Settings) -> int:
    """asyncio's debug mode in dev mode reports callbacks slower than 100 ms (D33)."""
    return asyncio.run(main(settings), debug=settings.dev_mode)
