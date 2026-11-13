"""announcements.post (WP2.9, D41): an embed in a channel, posted by a member who may manage messages."""

from typing import Any

import discord
import pytest

from teapot.core.registry import ActionFailed, Refused
from teapot.testing import FakeChannel, FakeVoiceChannel, PluginHarness
from teapot_announcements import Posted, plugin


async def harness_with_channel(teapot_harness: Any, **channel: Any) -> tuple[PluginHarness, FakeChannel]:
    harness: PluginHarness = await teapot_harness(plugin)
    return harness, harness.guild.add_channel(FakeChannel(**channel))


async def test_posts_the_announcement_as_an_embed(teapot_harness: Any) -> None:
    harness, channel = await harness_with_channel(teapot_harness)
    raw = {
        "channel": str(channel.id),
        "title": "Bingo starts",
        "body": "Teams are up.\nGood luck!",
        "colour": "green",
    }
    out = await harness.invoke("announcements.post", raw)
    (message,) = channel.sent
    assert message.embed is not None
    assert (message.embed.title, message.embed.description) == ("Bingo starts", "Teams are up.\nGood luck!")
    assert message.embed.colour == discord.Colour.green()
    assert out == Posted(message_id=message.id, url=message.jump_url)


async def test_the_colour_defaults_to_blurple(teapot_harness: Any) -> None:
    harness, channel = await harness_with_channel(teapot_harness)
    await harness.invoke("announcements.post", {"channel": str(channel.id), "title": "t", "body": "b"})
    assert channel.sent[0].embed is not None and channel.sent[0].embed.colour == discord.Colour.blurple()


async def test_an_unknown_channel_is_told_to_the_member(teapot_harness: Any) -> None:
    harness, _ = await harness_with_channel(teapot_harness)
    with pytest.raises(ActionFailed) as caught:
        await harness.invoke("announcements.post", {"channel": "123", "title": "t", "body": "b"})
    assert caught.value.public_message == "That channel is not a text channel in this server."


async def test_a_channel_the_bot_cannot_post_in_is_told_to_the_member(teapot_harness: Any) -> None:
    harness, channel = await harness_with_channel(teapot_harness, forbidden=True)
    with pytest.raises(ActionFailed) as caught:
        await harness.invoke("announcements.post", {"channel": str(channel.id), "title": "t", "body": "b"})
    assert caught.value.public_message == "I am not allowed to post in that channel."


async def test_posting_needs_manage_messages(teapot_harness: Any) -> None:
    harness, channel = await harness_with_channel(teapot_harness)
    member = harness.guild.add_member(discord.Permissions(send_messages=True))
    with pytest.raises(Refused) as caught:
        await harness.invoke(
            "announcements.post", {"channel": str(channel.id), "title": "t", "body": "b"}, user=member.id
        )
    assert caught.value.code == "forbidden"


async def test_a_body_over_discords_limit_is_refused(teapot_harness: Any) -> None:
    harness, channel = await harness_with_channel(teapot_harness)
    with pytest.raises(Refused) as caught:
        await harness.invoke(
            "announcements.post", {"channel": str(channel.id), "title": "t", "body": "x" * 4001}
        )
    assert caught.value.code == "invalid_input"


def test_the_reply_links_to_the_post() -> None:
    spec = next(iter(_actions().values()))
    assert spec.render is not None
    assert spec.render(Posted(message_id=1, url="https://discord.com/x")) == "Posted: https://discord.com/x"


def _actions() -> dict[str, Any]:
    collected: dict[str, Any] = {}

    class Collect:
        def action(self, spec: Any) -> None:
            collected[spec.name] = spec

        def job(self, name: str, handler: Any) -> None:
            raise AssertionError("announcements has no jobs yet")

    plugin.setup(Collect())
    return collected


async def test_a_channel_that_takes_no_messages_is_told_to_the_member(teapot_harness: Any) -> None:
    harness: PluginHarness = await teapot_harness(plugin)
    voice = harness.guild.add_channel(FakeVoiceChannel())
    with pytest.raises(ActionFailed) as caught:
        await harness.invoke("announcements.post", {"channel": str(voice.id), "title": "t", "body": "b"})
    assert caught.value.public_message == "That channel is not a text channel in this server."
