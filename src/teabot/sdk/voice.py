"""Voice (D54): the server's one voice connection, which a plugin reaches through `ctx.voice`.

- A bot has one voice connection per server, so the plugin that joins holds it until it leaves, and another
  plugin's `join` is refused meanwhile.
- `play` takes the audio as 20 ms Opus packets at 48 kHz, as Discord sends them. The core plays what the iterable
  yields, on a thread of its own, so it may block, such as while reading a stream. Decoding is the plugin's work,
  with whatever packages it depends on.
- When a track runs out or fails, the plugin's `@plugin.on_track_end` runs as a job. After a restart, the next
  process runs its `@plugin.on_voice_resume` for each server it was in, and the plugin joins and plays again from
  its own tables.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from teabot.sdk.guild import VoiceChannel

type Packets = Iterable[bytes]
"""Audio for `play`: one Opus packet per item, each 20 ms of 48 kHz stereo. It ends when the iterable does."""


@dataclass(frozen=True)
class VoiceState:
    """The bot's voice connection in one server.

    - `channel_id` is the channel it is in, and `plugin_id` the plugin that joined it.
    - `track` is what the plugin named the audio it last played, while that audio is playing or paused.
    - `paused` is whether that audio is paused.
    """

    channel_id: int
    plugin_id: str
    track: str | None = None
    paused: bool = False

    @property
    def playing(self) -> bool:
        """Whether audio is playing now, not paused."""
        return self.track is not None and not self.paused


class Voice(Protocol):
    """The server's voice connection, as one plugin sees it. Each method raises `ActionError` with the reason in
    plain words when Discord or another plugin would stop it."""

    @property
    def state(self) -> VoiceState | None:
        """The bot's connection in this server, whichever plugin holds it, or None when it is in no channel."""
        ...

    async def join(self, channel: VoiceChannel, /) -> None:
        """Join `channel`, or move there when already in another one. Refused while another plugin holds the
        connection, or when the bot may not connect and speak there."""
        ...

    async def play(self, packets: Packets, /, *, track: str) -> None:
        """Play `packets`, stopping what was playing without running `on_track_end` for it. `track` names the
        audio, such as a row's ID, and comes back to `on_track_end`. Refused before `join`."""
        ...

    async def pause(self) -> None:
        """Pause what is playing. Nothing happens when nothing is."""
        ...

    async def resume(self) -> None:
        """Carry on with paused audio. Nothing happens when nothing is paused."""
        ...

    async def stop(self) -> None:
        """Stop what is playing, without running `on_track_end`, and stay in the channel."""
        ...

    async def leave(self) -> None:
        """Stop and leave the channel. Nothing happens when the bot is in none."""
        ...
