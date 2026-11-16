"""A plugin reads anyone's message, with its files, finds who reacted with an emoji, and sees which channels are
age-restricted, threads among them."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import discord
import pytest

from teabot.sdk import Attachment, Context, EmptyConfig, File, Plugin, Reaction, ReceivedMessage
from teabot.sdk._views import GuildView, guild_view
from teabot.testing import HarnessFactory, PluginHarness
from teabot.testing.fakes import FakeChannel

plugin = Plugin("reader")
type Ctx = Context[EmptyConfig]
read: list[object] = []


@plugin.on_reaction_add
async def reacted(ctx: Ctx, reaction: Reaction) -> None:
    channel = ctx.guild.get_text_channel(reaction.channel_id)
    assert channel is not None
    read.append(await channel.read_message(reaction.message_id))
    read.append(await channel.reactors(reaction.message_id, reaction.emoji))


@pytest.fixture
async def harness(teabot_harness: HarnessFactory) -> PluginHarness:
    read.clear()
    return await teabot_harness(plugin)


async def test_a_message_is_read_with_its_files_and_who_reacted(harness: PluginHarness) -> None:
    channel = harness.guild.add_channel(FakeChannel(name="drops"))
    author = harness.guild.add_member(discord.Permissions.none())
    posted = await harness.post(channel, author, "twisted bow!", files=[File("tbow.png", b"png")])
    await harness.react(posted, harness.member, "⭐")
    url = "https://cdn.discordapp.com/attachments/0/0/tbow.png"
    picture = Attachment("tbow.png", url, "image/png")
    assert read == [
        ReceivedMessage(posted.id, channel.id, author.id, "twisted bow!", (picture,)),
        (harness.member.id,),
    ]
    assert picture.image and not Attachment("log.txt", url, "text/plain").image


async def test_reactors_are_oldest_first_without_bots_or_those_who_took_theirs_off(
    harness: PluginHarness,
) -> None:
    channel = harness.guild.add_channel(FakeChannel(name="chat"))
    first = harness.guild.add_member(discord.Permissions.none())
    bot = harness.guild.add_member(discord.Permissions.none())
    bot.bot = True
    posted = await harness.post(channel, first, "gz")
    posted.react(bot, "⭐")
    await harness.react(posted, first, "⭐")
    await harness.react(posted, harness.member, "⭐")
    await harness.react(posted, first, "🔥")
    assert read[-1] == (first.id,)
    assert read[-3] == (first.id, harness.member.id)
    await harness.react(posted, first, "⭐", remove=True)
    view = guild_view(harness.guild).get_text_channel(channel.id)
    assert view is not None
    assert await view.reactors(posted.id, "⭐") == (harness.member.id,)
    assert await view.reactors(posted.id, "💀") == ()


async def test_a_gone_message_reads_as_none(harness: PluginHarness) -> None:
    channel = harness.guild.add_channel(FakeChannel(name="chat"))
    view = guild_view(harness.guild).get_text_channel(channel.id)
    assert view is not None
    assert await view.read_message(12345) is None
    assert await view.reactors(12345, "⭐") == ()


def test_a_message_knows_when_it_was_posted() -> None:
    # Discord's own example ID, from its documentation of snowflakes.
    message = ReceivedMessage(175928847299117063, 1, 2, "")
    assert message.created_at == datetime(2016, 4, 30, 11, 18, 25, 796000, tzinfo=UTC)


async def test_a_channel_says_whether_it_is_age_restricted(harness: PluginHarness) -> None:
    safe = harness.guild.add_channel(FakeChannel(name="chat"))
    spicy = harness.guild.add_channel(FakeChannel(name="spicy", nsfw=True))
    found = [guild_view(harness.guild).get_channel(c.id) for c in (safe, spicy)]
    assert [c.nsfw for c in found if c is not None] == [False, True]


def test_a_thread_is_found_as_a_channel() -> None:
    thread = SimpleNamespace(
        id=7, name="raid night", type="public_thread", send=lambda: None, is_nsfw=lambda: True
    )

    def no_channel(channel_id: int) -> None:
        return None

    def channel_or_thread(channel_id: int) -> Any:
        return thread if channel_id == 7 else None

    raw: Any = SimpleNamespace(id=1, get_channel=no_channel, get_channel_or_thread=channel_or_thread)
    guild = GuildView(raw)
    channel = guild.get_channel(7)
    assert channel is not None and channel.nsfw
    assert guild.get_text_channel(7) is not None
