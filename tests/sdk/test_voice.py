"""Voice (D53): one connection per server, held by the plugin that joined, playing the plugin's Opus packets."""

import importlib.metadata
from collections.abc import Iterator

import discord
import pytest

from teabot.adapters.schema import slash_fields
from teabot.core.voice import davey_warning
from teabot.sdk import READ, ActionError, Context, EmptyConfig, Plugin, VoiceChannel
from teabot.testing import ActionFailed, FakeVoiceChannel, HarnessFactory, PluginHarness

plugin = Plugin("jukebox")
type Ctx = Context[EmptyConfig]
heard: list[str] = []


def tones(name: str, count: int) -> Iterator[bytes]:
    """Packets that say which track and which packet they are."""
    for n in range(count):
        yield f"{name}:{n}".encode()


@plugin.action()
async def join(ctx: Ctx, channel: VoiceChannel | None = None) -> str:
    """Join a voice channel.

    Args:
        channel: Where to play; the one you are in when left out.
    """
    if channel is None:
        member = await ctx.guild.get_member(ctx.actor.user_id)
        found = member.voice_channel_id if member is not None else None
        channel = ctx.guild.get_voice_channel(found) if found is not None else None
    if channel is None:
        raise ActionError("Join a voice channel first, or name one.")
    await ctx.voice.join(channel)
    return f"Joined {channel.name}."


@plugin.action()
async def play(ctx: Ctx, track: str, packets: int = 3) -> str:
    """Play a track.

    Args:
        track: Its name.
        packets: How many packets it has.
    """
    await ctx.voice.play(tones(track, packets), track=track)
    return f"Playing {track}."


@plugin.action()
async def pause(ctx: Ctx) -> str:
    """Pause."""
    await ctx.voice.pause()
    return "Paused."


@plugin.action()
async def resume(ctx: Ctx) -> str:
    """Resume."""
    await ctx.voice.resume()
    return "Resumed."


@plugin.action()
async def stop(ctx: Ctx) -> str:
    """Stop."""
    await ctx.voice.stop()
    return "Stopped."


@plugin.action()
async def leave(ctx: Ctx) -> str:
    """Leave."""
    await ctx.voice.leave()
    return "Left."


@plugin.action(risk=READ)
async def now(ctx: Ctx) -> str:
    """What is playing."""
    state = ctx.voice.state
    if state is None:
        return "Not in voice."
    return f"{state.plugin_id} in {state.channel_id}: {state.track} playing={state.playing} paused={state.paused}"


@plugin.on_track_end
async def next_track(ctx: Ctx, track: str, error: str | None) -> None:
    heard.append(f"ended {track} error={error}")
    if track == "first":
        await ctx.voice.play(tones("second", 2), track="second")


@plugin.on_voice_resume
async def carry_on(ctx: Ctx, channel: VoiceChannel | None) -> None:
    heard.append(f"resume {channel.name if channel else None}")
    if channel is not None:
        await ctx.voice.join(channel)
        await ctx.voice.play(tones("again", 1), track="again")


@plugin.on_voice_alone
async def alone(ctx: Ctx, channel: VoiceChannel | None) -> None:
    heard.append(
        f"alone in {channel.name if channel else None} with {len(channel.listener_ids) if channel else 0}"
    )


async def in_voice(teabot_harness: HarnessFactory) -> tuple[PluginHarness, FakeVoiceChannel]:
    heard.clear()
    harness = await teabot_harness(plugin)
    lounge = harness.guild.add_channel(FakeVoiceChannel(name="lounge"))
    harness.member.voice_channel = lounge
    return harness, lounge


async def session(harness: PluginHarness) -> tuple[str, int] | None:
    row = await harness.admin.fetchrow(
        "SELECT plugin_id, channel_id FROM core.voice_sessions WHERE guild_id = $1", harness.guild.id
    )
    return (row["plugin_id"], row["channel_id"]) if row is not None else None


async def test_joining_takes_the_members_channel_and_records_the_session(
    teabot_harness: HarnessFactory,
) -> None:
    harness, lounge = await in_voice(teabot_harness)
    assert await harness.call(join) == "Joined lounge."
    assert harness.voice_connection.channel is lounge
    assert harness.guild.me in lounge.members
    assert await session(harness) == ("jukebox", lounge.id)


async def test_a_named_channel_is_joined_and_another_moves_the_bot(teabot_harness: HarnessFactory) -> None:
    harness, lounge = await in_voice(teabot_harness)
    stage = harness.guild.add_channel(FakeVoiceChannel(name="raids"))
    await harness.call(join, channel=lounge)
    await harness.call(join, channel=stage)
    assert harness.voice_connection.moves == [stage.id]
    assert await session(harness) == ("jukebox", stage.id)


async def test_playing_hands_the_packets_to_the_connection(teabot_harness: HarnessFactory) -> None:
    harness, _ = await in_voice(teabot_harness)
    await harness.call(join)
    await harness.call(play, track="first", packets=3)
    assert harness.voice_connection.take(2) == [b"first:0", b"first:1"]
    assert (await harness.call(now)).endswith("first playing=True paused=False")


async def test_a_track_that_runs_out_runs_on_track_end_which_plays_the_next(
    teabot_harness: HarnessFactory,
) -> None:
    harness, _ = await in_voice(teabot_harness)
    await harness.call(join)
    await harness.call(play, track="first")
    await harness.end_track()
    assert heard == ["ended first error=None"]
    assert harness.voice_connection.take() == [b"second:0", b"second:1"]


async def test_a_failed_track_carries_its_error(teabot_harness: HarnessFactory) -> None:
    harness, _ = await in_voice(teabot_harness)
    await harness.call(join)
    await harness.call(play, track="broken")
    await harness.end_track(OSError("stream closed"))
    assert heard == ["ended broken error=OSError: stream closed"]


async def test_audio_the_plugin_stops_or_replaces_does_not_end_as_an_event(
    teabot_harness: HarnessFactory,
) -> None:
    harness, _ = await in_voice(teabot_harness)
    await harness.call(join)
    await harness.call(play, track="one")
    await harness.call(play, track="two")
    await harness.call(stop)
    assert harness.voice_service is not None
    await harness.voice_service.settle()
    await harness.run_jobs()
    assert heard == []
    assert [t.stopped for t in harness.voice_connection.tracks] == [True, True]
    assert (
        await harness.call(now)
        == f"jukebox in {harness.voice_connection.channel_id}: None playing=False paused=False"
    )


async def test_pausing_and_resuming(teabot_harness: HarnessFactory) -> None:
    harness, _ = await in_voice(teabot_harness)
    await harness.call(join)
    await harness.call(play, track="first")
    await harness.call(pause)
    assert harness.voice_connection.paused
    assert (await harness.call(now)).endswith("playing=False paused=True")
    await harness.call(resume)
    assert not harness.voice_connection.paused


async def test_playing_before_joining_is_refused(teabot_harness: HarnessFactory) -> None:
    harness, _ = await in_voice(teabot_harness)
    with pytest.raises(ActionFailed, match="Join one first"):
        await harness.call(play, track="first")


async def test_a_channel_the_bot_may_not_speak_in_is_refused(teabot_harness: HarnessFactory) -> None:
    harness, lounge = await in_voice(teabot_harness)
    lounge.refuse_speak = True
    with pytest.raises(ActionFailed, match="not allowed to speak in"):
        await harness.call(join)
    assert await session(harness) is None


async def test_another_plugin_cannot_join_or_play_while_one_holds_the_connection(
    teabot_harness: HarnessFactory,
) -> None:
    harness, lounge = await in_voice(teabot_harness)
    await harness.call(join)
    other = harness.voice_service.bound("radio", harness.guild.id)  # type: ignore[union-attr]
    with pytest.raises(ActionError, match="for the jukebox plugin"):
        await other.join(lounge)  # pyright: ignore[reportArgumentType]
    with pytest.raises(ActionError, match="belongs to the jukebox plugin"):
        await other.play(iter([b"x"]), track="x")


async def test_leaving_forgets_the_session(teabot_harness: HarnessFactory) -> None:
    harness, lounge = await in_voice(teabot_harness)
    await harness.call(join)
    await harness.call(play, track="first")
    await harness.call(leave)
    assert await session(harness) is None
    assert harness.guild.me not in lounge.members
    assert await harness.call(now) == "Not in voice."


async def test_a_disconnect_by_someone_else_ends_the_session_without_an_event(
    teabot_harness: HarnessFactory,
) -> None:
    harness, _ = await in_voice(teabot_harness)
    await harness.call(join)
    await harness.call(play, track="first")
    service = harness.voice_service
    assert service is not None
    await service.bot_moved(harness.guild.id, None)
    await harness.voice_connection.disconnect()
    await service.settle()
    await harness.run_jobs()
    assert heard == []
    assert await session(harness) is None


async def test_after_a_restart_the_plugin_resumes_in_its_channel(teabot_harness: HarnessFactory) -> None:
    harness, lounge = await in_voice(teabot_harness)
    await harness.call(join)
    await harness.call(play, track="first")
    await harness.restart_voice()
    assert heard == ["resume lounge"]
    assert harness.voice_connection.take() == [b"again:0"]
    assert await session(harness) == ("jukebox", lounge.id)


async def test_a_resume_whose_channel_is_gone_gets_none(teabot_harness: HarnessFactory) -> None:
    harness, lounge = await in_voice(teabot_harness)
    await harness.call(join)
    del harness.guild.channel_map[lounge.id]
    await harness.restart_voice()
    assert heard == ["resume None"]


def test_a_voice_channel_option_lists_only_voice_channels() -> None:
    option = slash_fields(join.inputs.model).options[0]
    assert option["type"] == 7
    assert option["channel_types"] == [2]


def test_a_davey_that_plays_silence_is_warned_about(monkeypatch: pytest.MonkeyPatch) -> None:
    versions = {"davey": "0.2.0"}
    monkeypatch.setattr(importlib.metadata, "version", versions.__getitem__)
    assert "listeners may hear silence" in (davey_warning() or "")
    versions["davey"] = "0.1.7"
    assert davey_warning() is None


async def test_the_last_member_leaving_tells_the_plugin_it_is_alone(teabot_harness: HarnessFactory) -> None:
    harness, lounge = await in_voice(teabot_harness)
    await harness.call(join)
    assert lounge.listener_ids == {harness.member.id}
    await harness.voice(harness.member, left=lounge)
    assert heard == ["alone in lounge with 0"]


async def test_a_member_leaving_while_others_stay_is_not_alone(teabot_harness: HarnessFactory) -> None:
    harness, lounge = await in_voice(teabot_harness)
    friend = harness.guild.add_member(discord.Permissions.none())
    friend.voice_channel = lounge
    bot = harness.guild.add_member(discord.Permissions.none(), bot=True)
    await harness.call(join)
    await harness.voice(harness.member, left=lounge)
    assert heard == []
    bot.voice_channel = lounge
    await harness.voice(friend, left=lounge)
    assert heard == ["alone in lounge with 0"]


async def test_an_empty_channel_the_bot_is_not_in_is_not_its_concern(teabot_harness: HarnessFactory) -> None:
    harness, _ = await in_voice(teabot_harness)
    raids = harness.guild.add_channel(FakeVoiceChannel(name="raids"))
    other = harness.guild.add_member(discord.Permissions.none())
    other.voice_channel = raids
    await harness.call(join)
    await harness.voice(other, left=raids)
    assert heard == []
