"""Members joining and leaving, heard by the plugins enabled in that server, each as a job of its own."""

import discord

from teabot.sdk import Context, EmptyConfig, Member, Plugin, User
from teabot.testing import FakeChannel, HarnessFactory

plugin = Plugin("welcome")
type Ctx = Context[EmptyConfig]
heard: list[str] = []


@plugin.on_member_join
async def welcome(ctx: Ctx, member: Member) -> None:
    heard.append(f"{ctx.actor.via}: joined {member.display_name}")
    await member.send(f"Welcome to {ctx.guild.name}!")


@plugin.on_member_leave
async def farewell(ctx: Ctx, user: User) -> None:
    heard.append(f"left {user.name} {user.id}")


async def test_a_member_joining_runs_the_handler_with_the_member(teabot_harness: HarnessFactory) -> None:
    heard.clear()
    harness = await teabot_harness(plugin)
    sam = harness.guild.add_member(discord.Permissions.none(), name="sam")
    await harness.join(sam)
    assert heard == ["event: joined sam"]
    assert sam.dms[0].content == "Welcome to guild!"


async def test_a_member_leaving_runs_the_handler_with_their_id(teabot_harness: HarnessFactory) -> None:
    heard.clear()
    harness = await teabot_harness(plugin)
    sam = harness.guild.add_member(discord.Permissions.none(), name="sam")
    await harness.leave(sam)
    assert heard == [f"left sam {sam.id}"]


async def test_a_plugin_turned_off_hears_nothing(teabot_harness: HarnessFactory) -> None:
    heard.clear()
    harness = await teabot_harness(plugin)
    await harness.invoke("plugins.disable", {"plugin": "welcome"})
    await harness.join(harness.guild.add_member(discord.Permissions.none()))
    assert heard == []


async def test_a_member_gone_by_the_time_the_job_runs_is_skipped(teabot_harness: HarnessFactory) -> None:
    heard.clear()
    harness = await teabot_harness(plugin)
    ghost = harness.guild.add_member(discord.Permissions.none())
    harness.guild.members.pop(ghost.id)
    await harness.join(ghost)
    assert heard == []
    assert harness.guild.add_channel(FakeChannel()).sent == []
