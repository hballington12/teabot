"""announcements.post (D41): an embed in a channel, posted by a member who may manage messages."""

import discord
import pytest

from teabot.plugins.announcements import Posted, plugin, post
from teabot.testing import ActionFailed, FakeChannel, FakeVoiceChannel, HarnessFactory, Refused


async def test_posts_the_announcement_as_an_embed(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    out = await harness.call(
        post, channel=channel, title="Bingo starts", body="Teams are up.\nGood luck!", colour="green"
    )
    (message,) = channel.sent
    assert message.embed is not None
    assert (message.embed.title, message.embed.description) == ("Bingo starts", "Teams are up.\nGood luck!")
    assert message.embed.colour == discord.Colour.green()
    assert out == Posted(message_id=message.id, url=message.jump_url)


async def test_an_announcement_mentions_nobody(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    await harness.call(post, channel=channel, title="Hi", body="@everyone come")
    mentions = channel.sent[0].allowed_mentions
    assert mentions is not None and mentions.to_dict()["parse"] == []


async def test_the_colour_defaults_to_blurple(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    await harness.call(post, channel=channel, title="t", body="b")
    assert channel.sent[0].embed is not None and channel.sent[0].embed.colour == discord.Colour.blurple()


@pytest.mark.parametrize("bad", ["missing", "voice"])
async def test_a_channel_that_takes_no_messages_is_told_to_the_member(
    teabot_harness: HarnessFactory, bad: str
) -> None:
    harness = await teabot_harness(plugin)
    channel_id = harness.guild.add_channel(FakeVoiceChannel()).id if bad == "voice" else 123
    with pytest.raises(ActionFailed) as caught:
        await harness.invoke("announcements.post", {"channel": str(channel_id), "title": "t", "body": "b"})
    assert caught.value.public_message == "That channel is not a text channel in this server."


async def test_a_channel_the_bot_cannot_post_in_is_told_to_the_member(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel(forbidden=True))
    with pytest.raises(ActionFailed) as caught:
        await harness.call(post, channel=channel, title="t", body="b")
    assert caught.value.public_message == "I am not allowed to post in that channel."


async def test_posting_needs_manage_messages(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    member = harness.guild.add_member(discord.Permissions(send_messages=True))
    with pytest.raises(Refused) as caught:
        await harness.as_member(member).call(post, channel=channel, title="t", body="b")
    assert caught.value.code == "forbidden"


async def test_a_body_over_discords_limit_is_refused(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    with pytest.raises(Refused) as caught:
        await harness.call(post, channel=channel, title="t", body="x" * 4001)
    assert caught.value.code == "invalid_input"


def test_the_reply_links_to_the_post() -> None:
    assert Posted(message_id=1, url="https://discord.com/x").render() == "Posted: https://discord.com/x"
