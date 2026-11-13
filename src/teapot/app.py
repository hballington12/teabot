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
from datetime import UTC, datetime
from typing import Protocol

import discord
import uvicorn

import teapot
from teapot.core.audit import POST_HANDLER, AuditMaintenance, PostAudit, ensure_read_partitions
from teapot.core.loader import LoadReport, discover, load
from teapot.core.maintenance import Maintenance
from teapot.core.processes import LockConnection, open_lock_connection
from teapot.core.queue import NOTIFY_CHANNEL, Queue
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
        self._shards: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def setup_hook(self) -> None:
        count, _url, _limits = await self.http.get_bot_gateway()
        self.shard_count = count
        self.shard_ids = list(range(count))
        await self.lock.take_shards(self.shard_ids)
        self._shards.set_result(count)
        log.info("shards locked", extra={"shard_count": count})

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
    queue.register("core", "maintenance", Maintenance(queue, daily=[AuditMaintenance(pools.core_db()).run]))
    await ensure_read_partitions(pools.core_db(), datetime.now(UTC).date(), days_ahead=7)
    runnable = ["core", *report.loaded]
    workers = Workers(queue, lambda: runnable)
    await lock.conn.add_listener(NOTIFY_CHANNEL, workers.on_notify)
    client = TeapotClient(lock)
    queue.register("core", POST_HANDLER, PostAudit(pools.core_db(), client))
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
