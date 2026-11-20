"""teabot-polls, through the real loader, migrations and call path, with the test clock."""

# --8<-- [start:imports]
import discord
import pytest

from teabot.testing import ActionFailed, FakeChannel, HarnessFactory, PluginHarness, Refused
from teabot_polls import Cfg, close, delete, list_, plugin, start, vote

# --8<-- [end:imports]


# --8<-- [start:helper]
async def started(harness: PluginHarness) -> tuple[FakeChannel, int]:
    channel = harness.guild.add_channel(FakeChannel())
    out = await harness.call(start, channel=channel, question="Tea or coffee?", options=["Tea", "Coffee"])
    return channel, out.poll


# --8<-- [end:helper]


# --8<-- [start:results]
async def test_the_results_are_posted_when_time_is_up(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, poll = await started(harness)
    voters = [harness.guild.add_member(discord.Permissions.none()) for _ in range(3)]
    for member, option in zip(voters, [1, 1, 2], strict=True):
        await harness.as_member(member).call(vote, poll=poll, option=option)
    await harness.advance(minutes=61)
    await harness.run_jobs()
    assert channel.sent[-1].content == "**Poll 1 has closed: Tea or coffee?**\n1. Tea: 2\n2. Coffee: 1"


# --8<-- [end:results]


async def test_starting_posts_the_numbered_options(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, poll = await started(harness)
    assert (
        channel.sent[0].content
        == f"**Poll {poll}: Tea or coffee?**\n1. Tea\n2. Coffee\nVote with `/polls vote poll:{poll}`."
    )


async def test_voting_again_changes_the_vote(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, poll = await started(harness)
    await harness.call(vote, poll=poll, option=1)
    assert await harness.call(vote, poll=poll, option=2) == "Your vote is option 2."
    (running,) = await harness.call(list_)
    assert running.voters == 1
    await harness.advance(minutes=61)
    await harness.run_jobs()
    assert (channel.sent[-1].content or "").endswith("1. Tea: 0\n2. Coffee: 1")


async def test_a_missing_option_or_a_closed_poll_is_refused(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    _, poll = await started(harness)
    with pytest.raises(ActionFailed, match="no option with that number"):
        await harness.call(vote, poll=poll, option=3)
    await harness.advance(minutes=61)
    with pytest.raises(ActionFailed, match="not running"):
        await harness.call(vote, poll=poll, option=1)


async def test_a_poll_takes_up_to_ten_options(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    ten = [f"Option {n}" for n in range(1, 11)]
    out = await harness.call(start, channel=channel, question="Which?", options=ten)
    assert await harness.call(vote, poll=out.poll, option=10) == "Your vote is option 10."
    with pytest.raises(Refused):
        await harness.call(start, channel=channel, question="Which?", options=[*ten, "Option 11"])


# --8<-- [start:suggestions]
async def test_voting_suggests_the_running_polls_then_the_chosen_polls_options(
    teabot_harness: HarnessFactory,
) -> None:
    harness = await teabot_harness(plugin)
    _, poll = await started(harness)
    polls = await harness.autocomplete(vote, "poll")
    assert [(c.name, c.value) for c in polls] == [(f"{poll}: Tea or coffee?", poll)]
    options = await harness.autocomplete(vote, "option", filled={"poll": poll})
    assert [(c.name, c.value) for c in options] == [("1: Tea", 1), ("2: Coffee", 2)]
    assert await harness.autocomplete(vote, "option") == []


# --8<-- [end:suggestions]


async def test_a_closed_poll_is_not_suggested(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    _, poll = await started(harness)
    await harness.advance(minutes=61)
    await harness.run_jobs()
    assert await harness.autocomplete(vote, "poll") == []
    assert await harness.autocomplete(vote, "option", filled={"poll": poll}) == []


# --8<-- [start:role]
async def test_only_the_voter_role_may_vote(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    voters = harness.guild.add_role("voters")
    await harness.configure(Cfg(voter_role=voters.id))
    _, poll = await started(harness)
    outsider = harness.guild.add_member(discord.Permissions.none())
    with pytest.raises(ActionFailed) as caught:
        await harness.as_member(outsider).call(vote, poll=poll, option=1)
    assert caught.value.public_message == "You need the voter role to vote here."


# --8<-- [end:role]


# --8<-- [start:delete]
async def test_deleting_shows_a_plan_and_stops_the_results(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, poll = await started(harness)
    plan = await harness.plan(delete, poll=poll)
    assert [(e.change, e.target) for e in plan.entries] == [("delete", "Tea or coffee?")]
    await harness.confirm(plan)
    assert await harness.call(list_) == []
    await harness.advance(minutes=61)
    await harness.run_jobs()
    assert len(channel.sent) == 1


# --8<-- [end:delete]


# --8<-- [start:twice]
async def test_closing_twice_posts_the_results_once(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, poll = await started(harness)
    await harness.advance(minutes=61)
    await harness.run_jobs()
    await harness.run_job(close.bind(poll=poll))
    assert len(channel.sent) == 2


# --8<-- [end:twice]


async def test_starting_needs_manage_messages(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    member = harness.guild.add_member(discord.Permissions.none())
    with pytest.raises(Refused) as caught:
        await harness.as_member(member).call(start, channel=channel, question="Q", options=["a", "b"])
    assert caught.value.code == "forbidden"
