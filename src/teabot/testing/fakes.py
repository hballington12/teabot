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
class _GuildChannel:
    """What every channel has: an id, a name, and the members who cannot see it."""

    id: int = field(default_factory=next_id)
    name: str = "channel"
    hidden_from: set[int] = field(default_factory=set[int])
    category: "FakeCategory | None" = None

    def permissions_for(self, member: "FakeMember", /) -> discord.Permissions:
        return discord.Permissions(view_channel=member.id not in self.hidden_from)


@dataclass
class FakeChannel(_GuildChannel):
    """A text channel that records what it is sent. A `forbidden` one refuses, as Discord does when the
    bot lacks permission there."""

    sent: list[FakeMessage] = field(default_factory=list[FakeMessage])
    forbidden: bool = False
    type: str = "text"

    async def send(self, content: str | None = None, *, embed: discord.Embed | None = None) -> FakeMessage:
        if self.forbidden:
            raise discord.Forbidden(cast(Any, _ForbiddenResponse()), "Missing Permissions")
        message = FakeMessage(next_id(), self.id, content, embed)
        self.sent.append(message)
        return message


@dataclass
class FakeVoiceChannel(_GuildChannel):
    """A channel that takes no messages, such as a voice channel."""

    type: str = "voice"


@dataclass
class FakeCategory(_GuildChannel):
    """A category: it groups channels and is listed among them, as in discord.py."""

    type: str = "category"


type AnyFakeChannel = FakeChannel | FakeVoiceChannel | FakeCategory


@dataclass
class FakeRole:
    id: int = field(default_factory=next_id)
    name: str = "role"


@dataclass
class FakeMember:
    id: int
    guild_permissions: discord.Permissions
    name: str = "member"
    nick: str | None = None

    @property
    def display_name(self) -> str:
        return self.nick or self.name


class _ForbiddenResponse:
    status = 403
    reason = "Forbidden"


class _NotFoundResponse:
    status = 404
    reason = "Not Found"


@dataclass
class FakeGuild:
    """A server. Members in `members` are cached; those in `fetchable` are only found over REST (D18)."""

    id: int = field(default_factory=next_id)
    members: dict[int, FakeMember] = field(default_factory=dict[int, FakeMember])
    fetchable: dict[int, FakeMember] = field(default_factory=dict[int, FakeMember])
    channel_map: dict[int, AnyFakeChannel] = field(default_factory=dict[int, AnyFakeChannel])
    roles: list[FakeRole] = field(default_factory=list[FakeRole])

    @property
    def channels(self) -> list[AnyFakeChannel]:
        """Every channel, as discord.py's `Guild.channels` lists them."""
        return list(self.channel_map.values())

    async def query_members(self, query: str, *, limit: int = 5) -> list[FakeMember]:
        """Gateway member search: members whose name or nickname starts with `query`, cached or not."""
        everyone = [*self.members.values(), *self.fetchable.values()]
        q = query.lower()
        found = [m for m in everyone if m.name.lower().startswith(q) or (m.nick or "").lower().startswith(q)]
        return found[:limit]

    def get_member(self, user_id: int, /) -> FakeMember | None:
        return self.members.get(user_id)

    async def fetch_member(self, user_id: int, /) -> FakeMember:
        if user_id not in self.fetchable:
            raise discord.NotFound(cast(Any, _NotFoundResponse()), "Unknown Member")
        return self.fetchable[user_id]

    def get_channel(self, channel_id: int, /) -> AnyFakeChannel | None:
        return self.channel_map.get(channel_id)

    def add_member(
        self,
        permissions: discord.Permissions,
        *,
        cached: bool = True,
        name: str = "member",
        nick: str | None = None,
    ) -> FakeMember:
        member = FakeMember(next_id(), permissions, name, nick)
        (self.members if cached else self.fetchable)[member.id] = member
        return member

    def add_channel[C: AnyFakeChannel](self, channel: C) -> C:
        self.channel_map[channel.id] = channel
        return channel

    def add_role(self, name: str) -> FakeRole:
        role = FakeRole(name=name)
        self.roles.append(role)
        return role


@dataclass
class FakeClient:
    """The bot's view of its servers and their channels."""

    guilds: dict[int, FakeGuild] = field(default_factory=dict[int, FakeGuild])
    command_overwrites: list[tuple[int | None, list[dict[str, Any]]]] = field(
        default_factory=list[tuple[int | None, list[dict[str, Any]]]]
    )

    async def overwrite_commands(self, guild_id: int | None, commands: list[dict[str, Any]], /) -> None:
        """Record a bulk overwrite: the global commands when `guild_id` is None, else one server's."""
        self.command_overwrites.append((guild_id, commands))

    def get_guild(self, guild_id: int, /) -> FakeGuild | None:
        return self.guilds.get(guild_id)

    def get_channel(self, channel_id: int, /) -> AnyFakeChannel | None:
        return next(
            (g.channel_map[channel_id] for g in self.guilds.values() if channel_id in g.channel_map), None
        )
