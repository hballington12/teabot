"""A fake voice connector (D54): `ctx.voice` in tests, without Discord, PyNaCl or a network.

Connections record what plugins play. Nothing is read from a track until the test says so: `connection.take(n)`
reads packets as the player would, and `harness.end_track()` ends the track as running out would.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field

from teabot.core.voice import After
from teabot.testing.fakes import FakeClient, FakeGuild, FakeVoiceChannel


@dataclass
class FakeTrack:
    """Audio a plugin played. `packets` holds what `take` has read of it so far."""

    source: Iterator[bytes]
    after: After
    packets: list[bytes] = field(default_factory=list[bytes])
    stopped: bool = False
    ended: bool = False


@dataclass
class FakeVoiceConnection:
    """The bot's connection in one fake server. `tracks` is every audio played on it, oldest first."""

    guild: FakeGuild
    channel: FakeVoiceChannel
    connected: bool = True
    paused: bool = False
    tracks: list[FakeTrack] = field(default_factory=list[FakeTrack])
    moves: list[int] = field(default_factory=list[int])

    @property
    def channel_id(self) -> int:
        return self.channel.id

    @property
    def current(self) -> FakeTrack | None:
        """The audio playing or paused, if any."""
        last = self.tracks[-1] if self.tracks else None
        return last if last is not None and not last.ended else None

    def is_connected(self) -> bool:
        return self.connected

    async def move_to(self, channel_id: int, /) -> None:
        channel = self.guild.get_channel(channel_id)
        assert isinstance(channel, FakeVoiceChannel)
        self.channel = channel
        self.guild.me.voice_channel = channel
        self.moves.append(channel_id)

    def play(self, packets: Iterator[bytes], after: After, /) -> None:
        assert self.current is None, "discord.py refuses to play over audio that is still playing"
        self.tracks.append(FakeTrack(packets, after))
        self.paused = False

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def stop(self) -> None:
        """As discord.py does: the audio ends, and its `after` runs."""
        track = self.current
        if track is not None:
            track.stopped = True
            self._end(track, None)

    async def disconnect(self) -> None:
        self.stop()
        self.connected = False
        self.guild.me.voice_channel = None

    def take(self, count: int | None = None) -> list[bytes]:
        """Read up to `count` packets of the current audio, or all of it, as the player would."""
        track = self.current
        assert track is not None, "nothing is playing"
        taken: list[bytes] = []
        while count is None or len(taken) < count:
            packet = next(track.source, None)
            if packet is None:
                break
            taken.append(packet)
        track.packets.extend(taken)
        return taken

    def finish(self, error: BaseException | None = None) -> None:
        """End the current audio as running out, or failing with `error`, would."""
        track = self.current
        assert track is not None, "nothing is playing"
        self._end(track, error)

    def _end(self, track: FakeTrack, error: BaseException | None) -> None:
        track.ended = True
        self.paused = False
        track.after(error)


@dataclass
class FakeVoice:
    """The fake connector: one `FakeVoiceConnection` per server the bot joins voice in."""

    client: FakeClient
    connections: dict[int, FakeVoiceConnection] = field(default_factory=dict[int, FakeVoiceConnection])
    joins: list[int] = field(default_factory=list[int])

    def current(self, guild_id: int, /) -> FakeVoiceConnection | None:
        connection = self.connections.get(guild_id)
        return connection if connection is not None and connection.connected else None

    def refusal(self, guild_id: int, channel_id: int, /) -> str | None:
        guild = self.client.get_guild(guild_id)
        if guild is None:
            return "The bot is not in that server."
        channel = guild.get_channel(channel_id)
        if not isinstance(channel, FakeVoiceChannel):
            return "That channel is not a voice channel in this server."
        allowed = channel.permissions_for(guild.me)
        if not allowed.connect:
            return f"I am not allowed to join {channel.mention}."
        if not allowed.speak:
            return f"I am not allowed to speak in {channel.mention}."
        return None

    async def connect(self, guild_id: int, channel_id: int, /) -> FakeVoiceConnection:
        guild = self.client.get_guild(guild_id)
        assert guild is not None
        channel = guild.get_channel(channel_id)
        assert isinstance(channel, FakeVoiceChannel)
        connection = FakeVoiceConnection(guild, channel)
        self.connections[guild_id] = connection
        guild.me.voice_channel = channel
        self.joins.append(channel_id)
        return connection
