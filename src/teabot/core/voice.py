"""Voice (D54): the bot's one voice connection in each server, which plugins reach through `ctx.voice`.

- `core.voice_sessions` names the plugin holding each server's connection, and its channel. Only that plugin may
  play, stop or leave; another plugin's `join` is refused while the connection is up.
- Audio is played as the plugin's Opus packets, through a `Connector`: discord.py's voice client in production, a
  fake in `teabot.testing`. The player reads the packets on its own thread, so a plugin's iterator may block.
- Audio that ends on its own, or fails, queues the holding plugin's `on_track_end` job. Audio the plugin stopped or
  replaced does not, and neither does audio cut off by leaving or by a shutdown.
- When the last member other than bots leaves the bot's channel, the holding plugin's `on_voice_alone` is queued.
- A shutdown disconnects without forgetting the sessions, so the next process queues each holding plugin's
  `on_voice_resume` once it is ready. A disconnect by anyone else, such as a moderator, forgets the session.
"""

import asyncio
import importlib.metadata
import logging
from collections.abc import Callable, Iterator, Mapping, Set
from dataclasses import dataclass
from typing import Any, Protocol

import discord

from teabot.core.queue import NewJob, Queue, ShardFilter
from teabot.db.pool import Database
from teabot.sdk import ActionError
from teabot.sdk.guild import VoiceChannel
from teabot.sdk.plugin import EventName
from teabot.sdk.voice import Packets, VoiceState

log = logging.getLogger(__name__)

SESSION = "SELECT plugin_id, channel_id FROM core.voice_sessions WHERE guild_id = $1"
SESSIONS = "SELECT guild_id, plugin_id, channel_id FROM core.voice_sessions"
SAVE = """
INSERT INTO core.voice_sessions (guild_id, plugin_id, channel_id) VALUES ($1, $2, $3)
ON CONFLICT (guild_id) DO UPDATE SET plugin_id = EXCLUDED.plugin_id, channel_id = EXCLUDED.channel_id,
    joined_at = now()
"""
MOVED = "UPDATE core.voice_sessions SET channel_id = $2 WHERE guild_id = $1"
FORGET = "DELETE FROM core.voice_sessions WHERE guild_id = $1"
FORGET_MINE = "DELETE FROM core.voice_sessions WHERE guild_id = $1 AND plugin_id = $2"
# Like a member event, the end of a track is about the moment; a handler that keeps failing is not retried for long.
EVENT_ATTEMPTS = 3
NOT_INSTALLED = "Voice is not installed on this instance. Its operator installs teabot with the voice extra."
NOT_JOINED = "I am not in a voice channel for this plugin here. Join one first."

type After = Callable[[BaseException | None], None]
"""What a connection calls when the audio it plays ends, with the error that ended it, or None. It may be called
from the player's thread."""


class Connection(Protocol):
    """One server's voice connection."""

    @property
    def channel_id(self) -> int: ...

    def is_connected(self) -> bool: ...

    async def move_to(self, channel_id: int, /) -> None: ...

    def play(self, packets: Iterator[bytes], after: After, /) -> None:
        """Play the packets, which nothing else is playing, and call `after` when they end."""
        ...

    def pause(self) -> None: ...

    def resume(self) -> None: ...

    def stop(self) -> None:
        """Stop the audio. `after` is still called for it."""
        ...

    async def disconnect(self) -> None: ...


class Connector(Protocol):
    """Makes and finds voice connections."""

    def current(self, guild_id: int, /) -> Connection | None:
        """The server's connection, or None when the bot is in no voice channel there."""
        ...

    def refusal(self, guild_id: int, channel_id: int, /) -> str | None:
        """Why the bot may not connect and speak in the channel, in plain words, or None when it may."""
        ...

    async def connect(self, guild_id: int, channel_id: int, /) -> Connection:
        """Join the channel. Raises `ActionError` when Discord or the installation stops it."""
        ...


@dataclass
class _Playing:
    """Audio a plugin started. `cut` is set when the plugin or the core ended it, so its end is not an event."""

    track: str
    paused: bool = False
    cut: bool = False


class VoiceService:
    """The core's side of `ctx.voice`, for every server and plugin. `listeners` are the voice events each plugin
    handles, so an event is queued only for a plugin that listens."""

    def __init__(
        self,
        db: Database,
        queue: Queue,
        connector: Connector,
        listeners: Mapping[str, Set[EventName]] | None = None,
    ) -> None:
        self.db = db
        self.queue = queue
        self.connector = connector
        self.listeners = dict(listeners or {})
        self.owners: dict[int, str] = {}
        self.playing: dict[int, _Playing] = {}
        self.pending: set[asyncio.Future[None]] = set()
        self.closing = False
        self.resumed = False

    def bound(self, plugin_id: str, guild_id: int) -> "GuildVoice":
        """`ctx.voice` for one plugin in one server."""
        return GuildVoice(self, plugin_id, guild_id)

    def _live(self, guild_id: int) -> Connection | None:
        connection = self.connector.current(guild_id)
        return connection if connection is not None and connection.is_connected() else None

    def state(self, guild_id: int) -> VoiceState | None:
        connection = self._live(guild_id)
        owner = self.owners.get(guild_id)
        if connection is None or owner is None:
            return None
        playing = self.playing.get(guild_id)
        if playing is None:
            return VoiceState(connection.channel_id, owner)
        return VoiceState(connection.channel_id, owner, playing.track, playing.paused)

    async def join(self, plugin_id: str, guild_id: int, channel_id: int) -> None:
        row = await self.db.fetchrow(SESSION, guild_id)
        connection = self._live(guild_id)
        holder = str(row["plugin_id"]) if row is not None else None
        if holder is not None and holder != plugin_id and connection is not None:
            raise ActionError(f"I am already in a voice channel here for the {holder} plugin.")
        refusal = self.connector.refusal(guild_id, channel_id)
        if refusal is not None:
            raise ActionError(refusal)
        if connection is None:
            connection = await self.connector.connect(guild_id, channel_id)
        elif connection.channel_id != channel_id:
            await connection.move_to(channel_id)
        await self.db.execute(SAVE, guild_id, plugin_id, channel_id)
        self.owners[guild_id] = plugin_id

    async def _held(self, plugin_id: str, guild_id: int) -> Connection:
        """The connection, when this plugin holds it; else `ActionError`."""
        connection = self._live(guild_id)
        holder = self.owners.get(guild_id)
        if holder is None and connection is not None:
            row = await self.db.fetchrow(SESSION, guild_id)
            holder = str(row["plugin_id"]) if row is not None else None
        if connection is None or holder is None:
            raise ActionError(NOT_JOINED)
        if holder != plugin_id:
            raise ActionError(f"The voice connection here belongs to the {holder} plugin.")
        self.owners[guild_id] = holder
        return connection

    def _cut(self, guild_id: int) -> None:
        """End what is playing, as the plugin's or the core's doing, so its end queues no event."""
        playing = self.playing.pop(guild_id, None)
        if playing is not None:
            playing.cut = True

    async def play(self, plugin_id: str, guild_id: int, packets: Packets, track: str) -> None:
        connection = await self._held(plugin_id, guild_id)
        if guild_id in self.playing:
            self._cut(guild_id)
            connection.stop()
        playing = _Playing(track)
        self.playing[guild_id] = playing
        connection.play(iter(packets), self._after(plugin_id, guild_id, playing))

    def _after(self, plugin_id: str, guild_id: int, playing: _Playing) -> After:
        loop = asyncio.get_running_loop()

        def ended(error: BaseException | None) -> None:
            loop.call_soon_threadsafe(self._start_ended, plugin_id, guild_id, playing, error)

        return ended

    def _start_ended(
        self, plugin_id: str, guild_id: int, playing: _Playing, error: BaseException | None
    ) -> None:
        future = asyncio.ensure_future(self._ended(plugin_id, guild_id, playing, error))
        self.pending.add(future)
        future.add_done_callback(self.pending.discard)

    async def _ended(
        self, plugin_id: str, guild_id: int, playing: _Playing, error: BaseException | None
    ) -> None:
        if playing.cut or self.closing:
            return
        if self.playing.get(guild_id) is playing:
            del self.playing[guild_id]
        if error is not None:
            log.warning(
                "voice track failed",
                extra={
                    "guild_id": guild_id,
                    "plugin_id": plugin_id,
                    "track": playing.track,
                    "error": repr(error),
                },
            )
        if self._live(guild_id) is None or "track_end" not in self.listeners.get(plugin_id, ()):
            return
        detail = f"{type(error).__name__}: {error}" if error is not None else None
        job = NewJob(
            plugin_id,
            "on_track_end",
            guild_id,
            payload={"track": playing.track, "error": detail},
            max_attempts=EVENT_ATTEMPTS,
        )
        await self.queue.schedule(job)

    async def settle(self) -> None:
        """Wait for the ends of tracks already reported, so their jobs are queued. For tests."""
        # A report reaches the loop through `call_soon_threadsafe`, so it starts on the next turn.
        await asyncio.sleep(0)
        while self.pending:
            await asyncio.gather(*list(self.pending))

    async def pause(self, plugin_id: str, guild_id: int) -> None:
        connection = await self._held(plugin_id, guild_id)
        playing = self.playing.get(guild_id)
        if playing is not None and not playing.paused:
            connection.pause()
            playing.paused = True

    async def resume(self, plugin_id: str, guild_id: int) -> None:
        connection = await self._held(plugin_id, guild_id)
        playing = self.playing.get(guild_id)
        if playing is not None and playing.paused:
            connection.resume()
            playing.paused = False

    async def stop(self, plugin_id: str, guild_id: int) -> None:
        connection = await self._held(plugin_id, guild_id)
        if guild_id in self.playing:
            self._cut(guild_id)
            connection.stop()

    async def leave(self, plugin_id: str, guild_id: int) -> None:
        connection = self._live(guild_id)
        if connection is None:
            # A session left over from before a restart, which the plugin gives up instead of resuming.
            await self.db.execute(FORGET_MINE, guild_id, plugin_id)
            if self.owners.get(guild_id) == plugin_id:
                del self.owners[guild_id]
            return
        await self._held(plugin_id, guild_id)
        self._cut(guild_id)
        await self.db.execute(FORGET, guild_id)
        self.owners.pop(guild_id, None)
        await connection.disconnect()

    async def bot_moved(self, guild_id: int, channel_id: int | None) -> None:
        """The bot's own voice state changed in a server: moved to `channel_id`, or out of voice when None. A
        disconnect the core did not make, such as a moderator's, ends the session."""
        if self.closing:
            return
        if channel_id is not None:
            await self.db.execute(MOVED, guild_id, channel_id)
            return
        self._cut(guild_id)
        self.owners.pop(guild_id, None)
        await self.db.execute(FORGET, guild_id)

    async def alone(self, guild_id: int, channel_id: int) -> bool:
        """The last member other than bots has left `channel_id`. When the bot is there, queue the holding
        plugin's `on_voice_alone`, if it handles it. Returns whether it was queued."""
        connection = self._live(guild_id)
        if connection is None or connection.channel_id != channel_id:
            return False
        holder = self.owners.get(guild_id)
        if holder is None:
            row = await self.db.fetchrow(SESSION, guild_id)
            holder = str(row["plugin_id"]) if row is not None else None
        if holder is None or "voice_alone" not in self.listeners.get(holder, ()):
            return False
        payload = {"channel_id": channel_id}
        await self.queue.schedule(
            NewJob(holder, "on_voice_alone", guild_id, payload=payload, max_attempts=EVENT_ATTEMPTS)
        )
        return True

    async def resume_sessions(self, shards: ShardFilter | None) -> int:
        """Once per process, when it is ready: queue `on_voice_resume` for each session on its shards, for the
        plugin that held it. A session whose plugin does not handle it is forgotten. Returns how many it queued."""
        if self.resumed:
            return 0
        self.resumed = True
        queued = 0
        for row in await self.db.fetch(SESSIONS):
            guild_id, plugin_id = int(row["guild_id"]), str(row["plugin_id"])
            if shards is not None and (guild_id >> 22) % shards.shard_count not in shards.shard_ids:
                continue
            if "voice_resume" not in self.listeners.get(plugin_id, ()):
                await self.db.execute(FORGET, guild_id)
                continue
            payload = {"channel_id": int(row["channel_id"])}
            await self.queue.schedule(
                NewJob(plugin_id, "on_voice_resume", guild_id, payload=payload, max_attempts=EVENT_ATTEMPTS)
            )
            queued += 1
        return queued

    async def close(self) -> None:
        """Disconnect everywhere for a shutdown, keeping the sessions for the next process to resume."""
        self.closing = True
        for guild_id in list(self.owners):
            self._cut(guild_id)
            connection = self._live(guild_id)
            if connection is not None:
                await connection.disconnect()


@dataclass(frozen=True)
class GuildVoice:
    """`ctx.voice`: the SDK's `Voice` for one plugin in one server."""

    service: VoiceService
    plugin_id: str
    guild_id: int

    @property
    def state(self) -> VoiceState | None:
        return self.service.state(self.guild_id)

    async def join(self, channel: VoiceChannel, /) -> None:
        await self.service.join(self.plugin_id, self.guild_id, channel.id)

    async def play(self, packets: Packets, /, *, track: str) -> None:
        await self.service.play(self.plugin_id, self.guild_id, packets, track)

    async def pause(self) -> None:
        await self.service.pause(self.plugin_id, self.guild_id)

    async def resume(self) -> None:
        await self.service.resume(self.plugin_id, self.guild_id)

    async def stop(self) -> None:
        await self.service.stop(self.plugin_id, self.guild_id)

    async def leave(self) -> None:
        await self.service.leave(self.plugin_id, self.guild_id)


class _PacketSource(discord.AudioSource):
    """The plugin's packets as discord.py's audio source. Already Opus, so discord.py sends them as they are."""

    def __init__(self, packets: Iterator[bytes]) -> None:
        self.packets = packets

    def is_opus(self) -> bool:
        return True

    def read(self) -> bytes:
        return next(self.packets, b"")


@dataclass(frozen=True)
class DiscordConnection:
    raw: discord.VoiceClient

    @property
    def channel_id(self) -> int:
        return int(self.raw.channel.id)

    def is_connected(self) -> bool:
        return self.raw.is_connected()

    async def move_to(self, channel_id: int, /) -> None:
        await self.raw.move_to(discord.Object(id=channel_id))

    def play(self, packets: Iterator[bytes], after: After, /) -> None:
        self.raw.play(_PacketSource(packets), after=after)

    def pause(self) -> None:
        self.raw.pause()

    def resume(self) -> None:
        self.raw.resume()

    def stop(self) -> None:
        self.raw.stop()

    async def disconnect(self) -> None:
        await self.raw.disconnect(force=True)


def davey_warning() -> str | None:
    """S8: discord.py 2.7 never calls davey 0.2's transition methods, so with davey 0.2 every listener hears silence
    while the bot shows as speaking. The voice extra pins davey below 0.2; this catches an install without it."""
    try:
        version = importlib.metadata.version("davey")
    except importlib.metadata.PackageNotFoundError:
        return None
    if version.startswith("0.1."):
        return None
    return (
        f"davey {version} is installed with discord.py {discord.__version__}; listeners may hear silence. "
        "teabot's voice extra pins davey below 0.2."
    )


class DiscordConnector:
    """Voice through discord.py, which needs teabot's voice extra: PyNaCl and davey."""

    def __init__(self, client: Any) -> None:
        self.client = client
        self.warned = False

    def _guild(self, guild_id: int) -> Any:
        return self.client.get_guild(guild_id)

    def current(self, guild_id: int, /) -> Connection | None:
        guild = self._guild(guild_id)
        raw = getattr(guild, "voice_client", None)
        return DiscordConnection(raw) if isinstance(raw, discord.VoiceClient) else None

    def refusal(self, guild_id: int, channel_id: int, /) -> str | None:
        guild = self._guild(guild_id)
        channel = guild.get_channel(channel_id) if guild is not None else None
        if not isinstance(channel, discord.VoiceChannel):
            return "That channel is not a voice channel in this server."
        allowed = channel.permissions_for(channel.guild.me)
        if not allowed.connect:
            return f"I am not allowed to join {channel.mention}."
        if not allowed.speak:
            return f"I am not allowed to speak in {channel.mention}."
        return None

    async def connect(self, guild_id: int, channel_id: int, /) -> Connection:
        if not self.warned and (warning := davey_warning()) is not None:
            log.warning(warning)
        self.warned = True
        channel = self._guild(guild_id).get_channel(channel_id)
        try:
            raw = await channel.connect(timeout=15, self_deaf=True)
        except RuntimeError:
            # discord.py raises this when PyNaCl or davey is missing.
            raise ActionError(NOT_INSTALLED) from None
        except TimeoutError:
            raise ActionError("Discord did not let me into the voice channel in time. Try again.") from None
        return DiscordConnection(raw)
