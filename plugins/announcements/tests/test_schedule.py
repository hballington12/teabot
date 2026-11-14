"""announcements.schedule (WP6.3): an announcement posted later, by a job on the queue (D31)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import discord
import pytest

from teapot.testing import ActionFailed, FakeChannel, FakeVoiceChannel, PluginHarness, Refused
from teapot_announcements import Scheduled, plugin, render_scheduled


async def setup(teapot_harness: Any) -> tuple[PluginHarness, FakeChannel]:
    harness: PluginHarness = await teapot_harness(plugin)
    return harness, harness.guild.add_channel(FakeChannel())


def raw(channel: Any, **extra: Any) -> dict[str, Any]:
    return {
        "channel": str(channel.id),
        "title": "Bingo starts",
        "body": "Good luck!",
        "in_minutes": 30,
    } | extra


async def due_now(harness: PluginHarness, job_id: int) -> None:
    await harness.admin.execute("UPDATE core.jobs SET run_at = now() WHERE id = $1", job_id)


async def test_scheduling_queues_the_post_for_later_and_sends_nothing_yet(teapot_harness: Any) -> None:
    harness, channel = await setup(teapot_harness)
    out = await harness.invoke("announcements.schedule", raw(channel))
    assert isinstance(out, Scheduled)
    assert timedelta(minutes=29) < out.at - datetime.now(UTC) <= timedelta(minutes=30)
    await harness.run_jobs()
    assert channel.sent == []
    run_at = await harness.admin.fetchval("SELECT run_at FROM core.jobs WHERE id = $1", out.job_id)
    assert run_at == out.at


async def test_when_it_is_due_the_job_posts_the_embed(teapot_harness: Any) -> None:
    harness, channel = await setup(teapot_harness)
    out = await harness.invoke("announcements.schedule", raw(channel, colour="gold"))
    assert isinstance(out, Scheduled)
    await due_now(harness, out.job_id)
    await harness.run_jobs()
    (message,) = channel.sent
    assert message.embed is not None
    assert (message.embed.title, message.embed.description, message.embed.colour) == (
        "Bingo starts",
        "Good luck!",
        discord.Colour.gold(),
    )


@pytest.mark.parametrize("bad", ["missing", "voice"])
async def test_the_channel_is_checked_when_scheduling(teapot_harness: Any, bad: str) -> None:
    harness, _ = await setup(teapot_harness)
    channel = harness.guild.add_channel(FakeVoiceChannel()) if bad == "voice" else FakeChannel()
    with pytest.raises(ActionFailed) as caught:
        await harness.invoke("announcements.schedule", raw(channel))
    assert caught.value.public_message == "That channel is not a text channel in this server."


async def test_a_channel_gone_by_then_fails_the_job_with_the_reason(teapot_harness: Any) -> None:
    harness, channel = await setup(teapot_harness)
    out = await harness.invoke("announcements.schedule", raw(channel))
    assert isinstance(out, Scheduled)
    del harness.guild.channel_map[channel.id]
    await due_now(harness, out.job_id)
    await harness.run_jobs()
    error = await harness.admin.fetchval("SELECT last_error FROM core.jobs WHERE id = $1", out.job_id)
    assert "is no longer a text channel" in error


async def test_a_channel_the_bot_may_no_longer_post_in_fails_the_job(teapot_harness: Any) -> None:
    harness, channel = await setup(teapot_harness)
    out = await harness.invoke("announcements.schedule", raw(channel))
    assert isinstance(out, Scheduled)
    channel.forbidden = True
    await due_now(harness, out.job_id)
    await harness.run_jobs()
    error = await harness.admin.fetchval("SELECT last_error FROM core.jobs WHERE id = $1", out.job_id)
    assert "not allowed to post" in error


@pytest.mark.parametrize("minutes", [0, 10081])
async def test_the_delay_is_a_minute_to_a_week(teapot_harness: Any, minutes: int) -> None:
    harness, channel = await setup(teapot_harness)
    with pytest.raises(Refused) as caught:
        await harness.invoke("announcements.schedule", raw(channel, in_minutes=minutes))
    assert caught.value.code == "invalid_input"


async def test_scheduling_needs_manage_messages(teapot_harness: Any) -> None:
    harness, channel = await setup(teapot_harness)
    member = harness.guild.add_member(discord.Permissions(send_messages=True))
    with pytest.raises(Refused) as caught:
        await harness.invoke("announcements.schedule", raw(channel), user=member.id)
    assert caught.value.code == "forbidden"


def test_the_reply_shows_when_in_discords_own_time_format() -> None:
    at = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
    assert (
        render_scheduled(Scheduled(job_id=7, at=at)) == f"Scheduled for <t:{int(at.timestamp())}:f> (job 7)."
    )
