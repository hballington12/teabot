"""Messages, reactions, role changes and voice moves reach the plugins that listen for them."""

import discord
import pytest

from teabot.sdk import (
    Context,
    EmptyConfig,
    Plugin,
    Reaction,
    ReceivedMessage,
    RoleChange,
    VoiceChange,
)
from teabot.testing import HarnessFactory, PluginHarness
from teabot.testing.fakes import FakeChannel, FakeVoiceChannel

plugin = Plugin("eventlog")
type Ctx = Context[EmptyConfig]
heard: list[object] = []


@plugin.on_message
async def message(ctx: Ctx, message: ReceivedMessage) -> None:
    heard.append(message)


@plugin.on_reaction_add
async def reacted(ctx: Ctx, reaction: Reaction) -> None:
    heard.append(("add", reaction))


@plugin.on_reaction_remove
async def unreacted(ctx: Ctx, reaction: Reaction) -> None:
    heard.append(("remove", reaction))


@plugin.on_member_roles
async def roles(ctx: Ctx, change: RoleChange) -> None:
    heard.append(change)


@plugin.on_voice
async def voice(ctx: Ctx, change: VoiceChange) -> None:
    heard.append(change)


@pytest.fixture
async def harness(teabot_harness: HarnessFactory) -> PluginHarness:
    heard.clear()
    return await teabot_harness(plugin)


async def test_a_message_and_its_reactions_are_heard(harness: PluginHarness) -> None:
    channel = harness.guild.add_channel(FakeChannel(name="chat"))
    author = harness.guild.add_member(discord.Permissions.none())
    posted = await harness.post(channel, author, "hello")
    assert heard == [ReceivedMessage(posted.id, channel.id, author.id, "hello")]
    await harness.react(posted, harness.member, "👍")
    await harness.react(posted, harness.member, "👍", remove=True)
    assert heard[1:] == [
        ("add", Reaction(posted.id, channel.id, harness.member.id, "👍")),
        ("remove", Reaction(posted.id, channel.id, harness.member.id, "👍")),
    ]


async def test_role_changes_and_voice_moves_come_with_the_member(harness: PluginHarness) -> None:
    raids = harness.guild.add_role("Raids")
    member = harness.guild.add_member(discord.Permissions.none())
    await harness.change_roles(member, added=[raids])
    change = heard[0]
    assert isinstance(change, RoleChange)
    assert (change.member.id, change.added, change.removed) == (member.id, (raids.id,), ())
    lounge = harness.guild.add_channel(FakeVoiceChannel(name="lounge"))
    await harness.voice(member, joined=lounge)
    moved = heard[1]
    assert isinstance(moved, VoiceChange)
    assert (moved.member.id, moved.left, moved.joined) == (member.id, None, lounge.id)


async def test_a_disabled_plugin_hears_nothing(harness: PluginHarness) -> None:
    await harness.invoke("plugins.disable", {"plugin": "eventlog"})
    channel = harness.guild.add_channel(FakeChannel(name="chat"))
    await harness.post(channel, harness.member, "anyone?")
    assert heard == []
