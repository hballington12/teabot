"""Posts queued in a transaction go out once it commits, and not at all when it rolls back."""

from typing import Any

import discord
import pytest
from pydantic import BaseModel

from teabot.sdk import Button, Context, EmptyConfig, Plugin, Post, TextChannel
from teabot.testing import HarnessFactory, PluginHarness
from teabot.testing.fakes import FakeChannel

plugin = Plugin("outboxtest")
type Ctx = Context[EmptyConfig]


class Posted(BaseModel):
    post: int


@plugin.action()
async def ping(ctx: Ctx, member: int) -> str:
    """Nothing, for a button.

    Args:
        member: Who.
    """
    return f"pinged {member}"


@plugin.action()
async def announce(ctx: Ctx, channel: TextChannel, text: str, fail: bool = False) -> Posted:
    """Queue a post.

    Args:
        channel: Where.
        text: What.
        fail: Roll back.
    """
    async with ctx.db.transaction() as tx:
        post = await tx.send(channel, text, ping=[42], buttons=[Button(ping.bind(member=42), label="Ping")])
        if fail:
            raise RuntimeError("rolled back")
    return Posted(post=post.id)


@plugin.action()
async def change(ctx: Ctx, post: int, text: str) -> str:
    """Edit a queued post.

    Args:
        post: Which.
        text: What.
    """
    async with ctx.db.transaction() as tx:
        await tx.edit(Post(post), text)
    return "changed"


@plugin.action()
async def remove(ctx: Ctx, post: int) -> str:
    """Delete a queued post.

    Args:
        post: Which.
    """
    async with ctx.db.transaction() as tx:
        await tx.delete(post)
    return "removed"


@plugin.action()
async def send_and_edit(ctx: Ctx, channel: TextChannel) -> str:
    """Send, then edit before it goes out.

    Args:
        channel: Where.
    """
    async with ctx.db.transaction() as tx:
        post = await tx.send(channel, "first")
        await tx.edit(post, embed=discord.Embed(title="second"))
    return "ok"


@pytest.fixture
async def harness(teabot_harness: HarnessFactory) -> PluginHarness:
    return await teabot_harness(plugin)


def channel(harness: PluginHarness, **options: Any) -> FakeChannel:
    return harness.guild.add_channel(FakeChannel(name="news", **options))


async def test_a_committed_post_goes_out_with_its_buttons_and_pings_only_whom_it_names(
    harness: PluginHarness,
) -> None:
    news = channel(harness)
    await harness.call(announce, channel=news, text="Hello @everyone")
    [message] = news.sent
    assert message.content == "Hello @everyone"
    assert message.allowed_mentions is not None
    assert message.allowed_mentions.everyone is False
    assert [b.label for b in message.buttons] == ["Ping"]
    assert await harness.press(message.buttons[0]) == "pinged 42"


async def test_a_rolled_back_transaction_posts_nothing(harness: PluginHarness) -> None:
    news = channel(harness)
    with pytest.raises(Exception, match="rolled back"):
        await harness.call(announce, channel=news, text="Hello", fail=True)
    await harness.run_jobs()
    assert news.sent == []


async def test_an_edit_and_a_delete_reach_the_message(harness: PluginHarness) -> None:
    news = channel(harness)
    out = await harness.call(announce, channel=news, text="Hello")
    await harness.call(change, post=out.post, text="Hello again")
    [message] = news.sent
    assert (message.content, message.edits, message.buttons) == ("Hello again", 1, [])
    await harness.call(remove, post=out.post)
    assert message.deleted


async def test_an_edit_before_the_post_goes_out_changes_what_goes_out(harness: PluginHarness) -> None:
    news = channel(harness)
    await harness.call(send_and_edit, channel=news)
    [message] = news.sent
    assert message.content is None
    assert message.embed is not None and message.embed.title == "second"
    await harness.run_jobs()
    assert (len(news.sent), message.edits) == (1, 0)


async def test_a_refused_post_is_recorded_and_not_retried(harness: PluginHarness) -> None:
    news = channel(harness, forbidden=True)
    out = await harness.call(announce, channel=news, text="Hello")
    error = await harness.admin.fetchval("SELECT error FROM core.posts WHERE id = $1", out.post)
    assert error == "I am not allowed to post in that channel."


async def test_another_plugins_post_cannot_be_edited(harness: PluginHarness) -> None:
    other = await harness.admin.fetchval(
        "INSERT INTO core.posts (guild_id, plugin_id, channel_id, message) VALUES ($1, 'other', 1, '{}') "
        "RETURNING id",
        harness.guild.id,
    )
    with pytest.raises(Exception, match="not one of this plugin's posts"):
        await harness.call(change, post=other, text="mine now")
