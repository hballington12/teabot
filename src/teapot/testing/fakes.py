"""Discord fakes for plugin and core tests (D45): just enough of a guild, its members and channels."""

import itertools
from dataclasses import dataclass, field
from typing import Any, cast

import discord

_ids = itertools.count(900_000_000_000_000_000)


def next_id() -> int:
    """A fresh snowflake-sized id."""
    return next(_ids)


@dataclass
class FakeMessage:
    id: int
    channel_id: int
    content: str | None
    embed: discord.Embed | None

    @property
    def jump_url(self) -> str:
        return f"https://discord.com/channels/0/{self.channel_id}/{self.id}"


@dataclass
class FakeChannel:
    """A text channel that records what it is sent."""

    id: int = field(default_factory=next_id)
    sent: list[FakeMessage] = field(default_factory=list[FakeMessage])

    async def send(self, content: str | None = None, *, embed: discord.Embed | None = None) -> FakeMessage:
        message = FakeMessage(next_id(), self.id, content, embed)
        self.sent.append(message)
        return message


@dataclass
class FakeMember:
    id: int
    guild_permissions: discord.Permissions


class _NotFoundResponse:
    status = 404
    reason = "Not Found"


@dataclass
class FakeGuild:
    """A server. Members in `members` are cached; those in `fetchable` are only found over REST (D18)."""

    id: int = field(default_factory=next_id)
    members: dict[int, FakeMember] = field(default_factory=dict[int, FakeMember])
    fetchable: dict[int, FakeMember] = field(default_factory=dict[int, FakeMember])
    channels: dict[int, FakeChannel] = field(default_factory=dict[int, FakeChannel])

    def get_member(self, user_id: int, /) -> FakeMember | None:
        return self.members.get(user_id)

    async def fetch_member(self, user_id: int, /) -> FakeMember:
        if user_id not in self.fetchable:
            raise discord.NotFound(cast(Any, _NotFoundResponse()), "Unknown Member")
        return self.fetchable[user_id]

    def get_channel(self, channel_id: int, /) -> FakeChannel | None:
        return self.channels.get(channel_id)

    def add_member(self, permissions: discord.Permissions, *, cached: bool = True) -> FakeMember:
        member = FakeMember(next_id(), permissions)
        (self.members if cached else self.fetchable)[member.id] = member
        return member

    def add_channel(self, channel: FakeChannel | None = None) -> FakeChannel:
        channel = channel or FakeChannel()
        self.channels[channel.id] = channel
        return channel


@dataclass
class FakeClient:
    """The bot's view of its servers and their channels."""

    guilds: dict[int, FakeGuild] = field(default_factory=dict[int, FakeGuild])

    def get_guild(self, guild_id: int, /) -> FakeGuild | None:
        return self.guilds.get(guild_id)

    def get_channel(self, channel_id: int, /) -> FakeChannel | None:
        return next((g.channels[channel_id] for g in self.guilds.values() if channel_id in g.channels), None)
