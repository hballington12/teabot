"""The SDK's Discord types, as the core's views over discord.py objects (or the fakes, which are shaped like them)."""

from typing import Any

import discord
import pytest

from teabot.sdk import ActionError, Guild
from teabot.sdk._views import guild_view
from teabot.testing import FakeChannel, FakeGuild, FakeVoiceChannel


def view(fake: FakeGuild) -> Guild:
    raw: Any = fake
    return guild_view(raw)


async def test_a_text_channel_sends_with_mentions_off_unless_pinged() -> None:
    fake = FakeGuild()
    channel = fake.add_channel(FakeChannel(name="bingo"))
    member = fake.add_member(discord.Permissions.none())
    found = view(fake).get_text_channel(channel.id)
    assert found is not None and (found.id, found.name, found.mention) == (
        channel.id,
        "bingo",
        f"<#{channel.id}>",
    )
    quiet = await found.send(f"hi {member.id}")
    loud = await found.send("you won", ping=[member.id])
    assert (quiet.id, quiet.channel_id) == (channel.sent[0].id, channel.id)
    assert quiet.jump_url == channel.sent[0].jump_url and loud.id == channel.sent[1].id
    quiet_mentions = channel.sent[0].allowed_mentions
    loud_mentions = channel.sent[1].allowed_mentions
    assert quiet_mentions is not None and quiet_mentions.to_dict()["parse"] == []
    assert loud_mentions is not None and loud_mentions.to_dict()["users"] == [member.id]


def test_a_channel_that_takes_no_messages_is_not_a_text_channel() -> None:
    fake = FakeGuild()
    voice = fake.add_channel(FakeVoiceChannel())
    assert view(fake).get_text_channel(voice.id) is None
    assert view(fake).get_text_channel(123) is None


async def test_a_member_is_found_in_the_cache_or_over_rest_with_their_roles() -> None:
    fake = FakeGuild()
    staff = fake.add_role("staff")
    cached = fake.add_member(discord.Permissions.none(), name="ann", roles=[staff])
    uncached = fake.add_member(discord.Permissions.none(), cached=False, nick="Bo")
    first = await view(fake).get_member(cached.id)
    second = await view(fake).get_member(uncached.id)
    assert first is not None and (first.display_name, first.mention, first.role_ids) == (
        "ann",
        f"<@{cached.id}>",
        frozenset({staff.id}),
    )
    assert second is not None and second.display_name == "Bo"
    assert await view(fake).get_member(42) is None


def test_a_role_is_found_by_id() -> None:
    fake = FakeGuild()
    staff = fake.add_role("staff")
    found = view(fake).get_role(staff.id)
    assert found is not None and (found.name, found.mention) == ("staff", f"<@&{staff.id}>")
    assert view(fake).get_role(1) is None


async def test_a_forbidden_send_says_so_in_the_members_words() -> None:
    fake = FakeGuild()
    channel = fake.add_channel(FakeChannel(forbidden=True))
    found = view(fake).get_text_channel(channel.id)
    assert found is not None
    with pytest.raises(ActionError, match="not allowed to post"):
        await found.send("hi")
