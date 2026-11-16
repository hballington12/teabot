"""`teabot run`: the real parts of a bot process, wired for `teabot.runtime` (D27, D33, D40).

The core migrates first. The Discord client logs in, and in `setup_hook`, before any shard connects, fixes the
shard count and takes the shard locks. `teabot.runtime` supervises from there. This module only opens the
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
from urllib.parse import urlsplit

import discord
import uvicorn

import teabot
from teabot.adapters.interactions import InteractionRouter, prune_drafts
from teabot.adapters.mcp import McpAdapter
from teabot.assembly import assemble
from teabot.cli.init import application_id
from teabot.core.audit import AuditMaintenance, ensure_read_partitions
from teabot.core.events import Events
from teabot.core.lifecycle import PURGE_GUILD, Guilds
from teabot.core.loader import LoadReport, discover, load
from teabot.core.maintenance import Maintenance
from teabot.core.processes import LockConnection, open_lock_connection
from teabot.core.queue import NOTIFY_CHANNEL, Queue, ShardFilter
from teabot.core.registry import Registry
from teabot.core.voice import VoiceService
from teabot.core.worker import Workers
from teabot.db.migrate import MigrationReport, PluginMigrations, migrate
from teabot.db.naming import Naming
from teabot.db.pool import ConnectionInfo, Credentials, Login, Pools, Timing, connect, create_pools
from teabot.health import Health
from teabot.runtime import Runtime, serve_until_stopped
from teabot.sdk._views import attachments
from teabot.sdk.plugin import EventName
from teabot.settings import Settings
from teabot.site.app import Site
from teabot.site.oauth import DiscordOAuth
from teabot.site.sessions import Sessions
from teabot.watchdog import watching
from teabot.web import build_app

log = logging.getLogger(__name__)

# Voice is an extra (D54), and teabot says itself what is missing when a plugin joins a channel, so discord.py's
# warnings about voice libraries are noise.
discord.VoiceClient.warn_nacl = False
discord.VoiceClient.warn_dave = False

SLOW_TRANSACTION_MS = 100.0


class Shard(Protocol):
    @property
    def latency(self) -> float: ...

    def is_closed(self) -> bool: ...


def shard_latencies(shards: Mapping[int, Shard], ready: bool) -> dict[int, float | None]:
    """Gateway latency per shard, or None for a shard that is not connected. Until the client is ready, its
    guild cache is still filling and calls would be refused, so every shard counts as not connected."""
    if not ready:
        return dict.fromkeys(shards)
    return {
        shard_id: None if shard.is_closed() or not math.isfinite(shard.latency) else shard.latency
        for shard_id, shard in shards.items()
    }


def token_or_exit(token: str) -> str:
    if not token:
        raise SystemExit("TEABOT_DISCORD_TOKEN is not set; put the bot token in teabot.env")
    return token


class TeabotClient(discord.AutoShardedClient):
    """The Discord client. Members are cached lazily (D25); interactions are routed by the core (D32)."""

    def __init__(self, lock: LockConnection, *, message_content: bool = False) -> None:
        intents = discord.Intents.default()
        intents.members = True
        # Privileged: the operator turns it on in the developer portal first, or Discord refuses the connection.
        intents.message_content = message_content
        super().__init__(
            intents=intents,
            chunk_guilds_at_startup=False,
            member_cache_flags=discord.MemberCacheFlags.from_intents(intents),
        )
        self.lock = lock
        self.router: InteractionRouter | None = None
        self.lifecycle: Guilds | None = None
        self.events: Events | None = None
        self.voice: VoiceService | None = None
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

    async def on_member_join(self, member: discord.Member) -> None:
        if self.events is not None:
            await self.events.fire(member.guild.id, "member_join", {"user_id": member.id})

    async def on_raw_member_remove(self, payload: discord.RawMemberRemoveEvent) -> None:
        """Raw, so a member who left while not cached is still heard."""
        await self._fire(
            payload.guild_id, "member_leave", {"user_id": payload.user.id, "name": payload.user.name}
        )

    async def _fire(self, guild_id: int | None, event: EventName, payload: dict[str, Any]) -> None:
        if self.events is not None and guild_id is not None and self.events.hears(event):
            await self.events.fire(guild_id, event, payload)

    async def on_message(self, message: discord.Message) -> None:
        """Messages in servers, from people: a bot's, teabot's own among them, is never heard, so plugins
        cannot answer each other in a loop."""
        if message.guild is None or message.author.bot:
            return
        payload = {
            "message_id": message.id,
            "channel_id": message.channel.id,
            "author_id": message.author.id,
            "content": message.content,
            "attachments": attachments(message),
        }
        await self._fire(message.guild.id, "message", payload)

    async def _reaction(self, payload: discord.RawReactionActionEvent, event: EventName) -> None:
        member = payload.member
        if (self.user is not None and payload.user_id == self.user.id) or (member is not None and member.bot):
            return
        data = {
            "message_id": payload.message_id,
            "channel_id": payload.channel_id,
            "user_id": payload.user_id,
            "emoji": str(payload.emoji),
        }
        await self._fire(payload.guild_id, event, data)

    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        await self._reaction(payload, "reaction_add")

    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        await self._reaction(payload, "reaction_remove")

    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        """Role changes. Discord's gateway sends the change for any member, but discord.py tells only of the
        members in its cache, which holds those seen since startup (D25)."""
        old, new = {r.id for r in before.roles}, {r.id for r in after.roles}
        if old == new:
            return
        payload = {"user_id": after.id, "added": sorted(new - old), "removed": sorted(old - new)}
        await self._fire(after.guild.id, "member_roles", payload)

    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        """Members moving, for plugins that listen and for the plugin holding a channel the bot is left alone in,
        and the bot's own moves, so a voice session follows it and ends when someone else disconnects it (D54)."""
        if before.channel == after.channel:
            return
        if self.user is not None and member.id == self.user.id:
            if self.voice is not None:
                await self.voice.bot_moved(member.guild.id, after.channel.id if after.channel else None)
            return
        if not member.bot:
            await self._member_moved(member, before.channel, after.channel)

    async def _member_moved(self, member: discord.Member, left: Any, joined: Any) -> None:
        payload = {"user_id": member.id, "left": _channel_id(left), "joined": _channel_id(joined)}
        await self._fire(member.guild.id, "voice", payload)
        # discord.py updates the channel's members before dispatching, so the leaver is already gone from them.
        if self.voice is not None and left is not None and not any(not m.bot for m in left.members):
            await self.voice.alone(member.guild.id, left.id)

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
        if self.voice is not None:
            resumed = await self.voice.resume_sessions(shards)
            log.info("voice sessions resumed", extra={"count": resumed})

    async def close(self) -> None:
        """Leave voice channels first, keeping their sessions, so the next process resumes them (D54)."""
        if self.voice is not None:
            await self.voice.close()
        await super().close()

    async def wait_for_shards(self) -> int:
        return await asyncio.shield(self._shards)


def public_hosts(settings: Settings) -> list[str]:
    """The host the reverse proxy serves teabot on, from `TEABOT_PUBLIC_URL`; local hosts are always allowed."""
    if settings.public_url is None:
        return []
    return [urlsplit(settings.public_url).netloc]


class EmbeddedServer(uvicorn.Server):
    """uvicorn inside teabot's loop. teabot owns the signals, so uvicorn must not capture them."""

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
        found = discover(blocked=settings.disabled_plugins)
        return await load(found, disabled=settings.disabled_plugins, migrate_with=migrator, lock=lock)
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
        await Sessions(pools.core_db()).prune()

    daily = [AuditMaintenance(pools.core_db()).run, prune]
    queue.register("core", "maintenance", Maintenance(queue, daily=daily))
    await ensure_read_partitions(pools.core_db(), datetime.now(UTC).date(), days_ahead=7)
    runnable = ["core", *report.loaded]
    workers = Workers(queue, lambda: runnable)
    await lock.conn.add_listener(NOTIFY_CHANNEL, workers.on_notify)
    client = TeabotClient(lock, message_content=settings.message_content)
    core = assemble(report, pools, queue, client, settings.public_url)
    client.lifecycle = Guilds(pools, queue, core.sync, timedelta(days=settings.guild_retention_days))
    client.events = core.events
    client.voice = core.voice
    queue.register("core", PURGE_GUILD, client.lifecycle.purge)
    log.info("command syncs queued", extra={"count": await core.sync.startup()})
    log.info("recurring jobs queued", extra={"servers": await core.recurring.startup()})
    client.router = InteractionRouter(core.registry, pools.core_db())
    health = Health(
        teabot.__version__,
        pools.core_db(),
        lambda: shard_latencies(client.shards, client.is_ready()),
        lambda: statuses,
    )
    config = uvicorn.Config(
        build_app(
            health,
            tokens=core.tokens,
            mcp=McpAdapter(core.registry, pools.core_db(), hosts=public_hosts(settings)),
            service=core.registry,
            site=site_for(settings, core.registry, pools, client, report),
        ),
        host=settings.http_host,
        port=settings.http_port,
        log_config=None,
        lifespan="on",
    )
    server = EmbeddedServer(config)
    return Runtime(
        token, teabot.__version__, pools, lock, workers, client, server, statuses, stop=stop, failed=failed
    )


def site_for(
    settings: Settings, registry: Registry, pools: Pools, client: Any, report: LoadReport
) -> Site | None:
    """The instance's site (D53), when it has a public address. Members can sign in when the operator also gives
    the OAuth2 client secret of its application, for Discord to send them back to `/auth/callback`."""
    if not settings.public_url:
        return None
    base = settings.public_url.rstrip("/")
    secret = settings.discord_client_secret.get_secret_value()
    client_id = application_id(settings.discord_token.get_secret_value())
    oauth = (
        DiscordOAuth(client_id, secret, f"{base}/auth/callback") if secret and client_id is not None else None
    )
    manifests = {plugin_id: loaded.plugin.manifest for plugin_id, loaded in report.loaded.items()}
    return Site(
        registry,
        Sessions(pools.core_db()),
        oauth,
        client,
        manifests,
        client_id,
        secure=base.startswith("https://"),
        pages_dir=settings.site_pages,
    )


def stop_on_signals(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    """Set `stop` on SIGINT and SIGTERM, so a shutdown closes the gateway and the pools cleanly."""

    def handle(_sig: int, _frame: object) -> None:
        loop.call_soon_threadsafe(stop.set)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            # Windows' event loops have no signal handlers, so this falls back to the process-wide handler,
            # which runs outside the loop and hands the stop back to it.
            signal.signal(sig, handle)


async def main(settings: Settings) -> int:
    """Open the real parts, run until stopped, and return the exit code. The watchdog is armed before the
    plugins load, so one that hangs while it is imported is caught too (D33)."""
    token = token_or_exit(settings.discord_token.get_secret_value())
    dog = watching(settings.loop_warn_seconds, settings.loop_limit_seconds, settings.startup_limit_seconds)
    dog.arm()
    rt = await _open_runtime(settings, token)
    heartbeat = asyncio.create_task(dog.beat())
    stop_on_signals(asyncio.get_running_loop(), rt.stop)
    try:
        return await serve_until_stopped(rt)
    finally:
        heartbeat.cancel()
        dog.disarm()
        await rt.pools.close()


def run(settings: Settings) -> int:
    """asyncio's debug mode in dev mode reports callbacks slower than 100 ms (D33)."""
    return asyncio.run(main(settings), debug=settings.dev_mode)


def _channel_id(channel: Any) -> int | None:
    return None if channel is None else int(channel.id)
