"""announcements.schedule: an announcement posted later, by a job on the queue (D31)."""

from datetime import UTC, datetime, timedelta

import discord
import pytest

from teabot.testing import FakeChannel, HarnessFactory, JobFailed, PluginHarness, Refused
from teabot_announcements import Scheduled, plugin, schedule


async def scheduled(harness: PluginHarness, channel: FakeChannel, **extra: str) -> Scheduled:
    colour = extra.get("colour", "blurple")
    assert colour in ("blurple", "green", "red", "gold")
    return await harness.call(
        schedule, channel=channel, title="Bingo starts", body="Good luck!", in_minutes=30, colour=colour
    )


async def test_scheduling_posts_nothing_until_it_is_due(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    out = await scheduled(harness, channel)
    assert timedelta(minutes=29) < out.at - datetime.now(UTC) <= timedelta(minutes=30)
    await harness.run_jobs()
    assert channel.sent == []
    await harness.advance(minutes=31)
    await harness.run_jobs()
    (message,) = channel.sent
    assert message.embed is not None and message.embed.title == "Bingo starts"


async def test_the_colour_reaches_the_later_post(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    await scheduled(harness, channel, colour="gold")
    await harness.advance(minutes=31)
    await harness.run_jobs()
    assert channel.sent[0].embed is not None and channel.sent[0].embed.colour == discord.Colour.gold()


async def test_a_channel_gone_by_then_fails_the_job_with_the_reason(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    await scheduled(harness, channel)
    del harness.guild.channel_map[channel.id]
    await harness.advance(minutes=31)
    with pytest.raises(JobFailed, match="is no longer a text channel"):
        await harness.run_jobs()


async def test_a_channel_the_bot_may_no_longer_post_in_fails_the_job(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    await scheduled(harness, channel)
    channel.forbidden = True
    await harness.advance(minutes=31)
    with pytest.raises(JobFailed, match="not allowed to post"):
        await harness.run_jobs()


@pytest.mark.parametrize("minutes", [0, 10081])
async def test_the_delay_is_a_minute_to_a_week(teabot_harness: HarnessFactory, minutes: int) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    with pytest.raises(Refused) as caught:
        await harness.call(schedule, channel=channel, title="t", body="b", in_minutes=minutes)
    assert caught.value.code == "invalid_input"


async def test_scheduling_needs_manage_messages(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    member = harness.guild.add_member(discord.Permissions(send_messages=True))
    with pytest.raises(Refused) as caught:
        await harness.as_member(member).call(schedule, channel=channel, title="t", body="b", in_minutes=5)
    assert caught.value.code == "forbidden"


def test_the_reply_shows_when_in_discords_own_time_format() -> None:
    at = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    assert Scheduled(job_id=7, at=at).render() == f"Scheduled for <t:{int(at.timestamp())}:f> (job 7)."
