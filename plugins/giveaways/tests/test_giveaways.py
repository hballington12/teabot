"""teabot-giveaways, through the real loader, migrations and call path, with the test clock."""

import discord
import pytest

from teabot.testing import ActionFailed, FakeChannel, HarnessFactory, PluginHarness, Refused
from teabot_giveaways import Cfg, cancel, draw, enter, list_, plugin, start


async def started(harness: PluginHarness, *, winners: int = 1, minutes: int = 30) -> tuple[FakeChannel, int]:
    channel = harness.guild.add_channel(FakeChannel())
    out = await harness.call(start, channel=channel, prize="A pet", winners=winners, minutes=minutes)
    return channel, out.giveaway


async def test_starting_announces_the_giveaway_and_how_to_enter(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, giveaway = await started(harness)
    content = channel.sent[0].content
    assert content is not None and "A pet" in content and f"giveaway:{giveaway}" in content


async def test_the_draw_announces_the_winners_when_time_is_up(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, giveaway = await started(harness, winners=2)
    players = [harness.guild.add_member(discord.Permissions.none()) for _ in range(3)]
    for player in players:
        assert await harness.as_member(player).call(enter, giveaway=giveaway) == "You're in. Good luck!"
    await harness.run_jobs()
    assert len(channel.sent) == 1
    await harness.advance(minutes=31)
    await harness.run_jobs()
    result = channel.sent[-1]
    pinged = result.allowed_mentions.to_dict()["users"] if result.allowed_mentions else []
    assert len(pinged) == 2 and set(pinged) <= {p.id for p in players}
    assert all(f"<@{w}>" in (result.content or "") for w in pinged)


async def test_a_second_draw_changes_nothing(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, giveaway = await started(harness)
    await harness.call(enter, giveaway=giveaway)
    await harness.advance(minutes=31)
    await harness.run_jobs()
    winners = await harness.admin.fetchval("SELECT count(*) FROM plugin_giveaways.entries WHERE won")
    await harness.run_job(draw.bind(giveaway=giveaway))
    assert len(channel.sent) == 2
    assert (
        await harness.admin.fetchval("SELECT count(*) FROM plugin_giveaways.entries WHERE won")
        == winners
        == 1
    )


async def test_nobody_entering_is_said_plainly(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, _ = await started(harness)
    await harness.advance(minutes=31)
    await harness.run_jobs()
    assert channel.sent[-1].content == "Nobody entered the giveaway for **A pet**."


async def test_a_member_enters_once_and_not_after_the_end(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    _, giveaway = await started(harness)
    await harness.call(enter, giveaway=giveaway)
    with pytest.raises(ActionFailed, match="already in"):
        await harness.call(enter, giveaway=giveaway)
    late = harness.guild.add_member(discord.Permissions.none())
    await harness.advance(minutes=31)
    with pytest.raises(ActionFailed, match="not running"):
        await harness.as_member(late).call(enter, giveaway=giveaway)


async def test_the_excluded_role_cannot_enter(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    staff = harness.guild.add_role("staff")
    await harness.configure(Cfg(excluded_role=staff.id))
    _, giveaway = await started(harness)
    member = harness.guild.add_member(discord.Permissions.none(), roles=[staff])
    with pytest.raises(ActionFailed) as caught:
        await harness.as_member(member).call(enter, giveaway=giveaway)
    assert caught.value.public_message == "Your role cannot enter giveaways here."


async def test_the_list_shows_running_giveaways_with_their_entrants(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    _, giveaway = await started(harness)
    await harness.call(enter, giveaway=giveaway)
    (running,) = await harness.call(list_)
    assert (running.id, running.prize, running.entrants) == (giveaway, "A pet", 1)


async def test_the_default_length_comes_from_config(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    await harness.configure(Cfg(default_minutes=90))
    channel = harness.guild.add_channel(FakeChannel())
    out = await harness.call(start, channel=channel, prize="A cape")
    (running,) = await harness.call(list_)
    assert running.ends_at == out.ends_at


async def test_cancelling_shows_a_plan_and_stops_the_draw(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, giveaway = await started(harness)
    plan = await harness.plan(cancel, giveaway=giveaway)
    assert [(e.change, e.target, e.detail) for e in plan.entries] == [("cancel", "A pet", "0 entrants")]
    await harness.confirm(plan)
    assert await harness.call(list_) == []
    await harness.advance(minutes=31)
    await harness.run_jobs()
    assert len(channel.sent) == 1


async def test_cancelling_an_unknown_giveaway_says_so(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    with pytest.raises(ActionFailed, match="No running giveaway has that number"):
        await harness.plan(cancel, giveaway=99)


async def test_starting_needs_manage_messages(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    member = harness.guild.add_member(discord.Permissions.none())
    with pytest.raises(Refused) as caught:
        await harness.as_member(member).call(start, channel=channel, prize="A pet")
    assert caught.value.code == "forbidden"
