"""The parts of a Discord server a plugin works with (D45). The core gives plugins these, never discord.py's own
objects, so plugin code types the same against Discord and against `teabot.testing`'s fakes.

- `Guild`: the server, to find its channels, roles and members, and to ban.
- `TextChannel`: a channel that takes messages. Its `send` mentions nobody unless `ping` names them.
- `Channel`: any channel, of any kind, to read.
- `Member`, `Role` and `Message`: what those lookups and sends return.

Every operation acts with the bot's own power; the plugin decides who may use it. Before calling Discord, each one
checks what Discord would refuse, such as a role above the bot's own, and raises `ActionError` with the reason in
plain words. Changes carry a reason for Discord's audit log, "via teabot: <action>" unless the plugin gives one.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

import discord

from teabot.sdk.components import Button
from teabot.sdk.permissions import Permission

type ChannelKind = Literal["text", "voice", "category", "forum", "stage", "thread", "announcement", "other"]


class Role(Protocol):
    """A role in the server."""

    @property
    def id(self) -> int:
        """The role's Discord ID."""
        ...

    @property
    def name(self) -> str:
        """The role's name."""
        ...

    @property
    def mention(self) -> str:
        """The role as a mention, such as `<@&123>`."""
        ...

    @property
    def position(self) -> int:
        """Its place in the role list: higher is more senior, and @everyone is 0."""
        ...

    @property
    def permissions(self) -> frozenset[Permission]:
        """The permissions it grants, by the names `needs=` uses, such as `"manage_messages"`."""
        ...

    @property
    def colour(self) -> int:
        """Its colour as an RGB number, 0 for none."""
        ...

    @property
    def managed(self) -> bool:
        """Whether Discord or an integration manages it, such as a bot's own role or the booster role. Nobody can
        give or take a managed role."""
        ...

    @property
    def mentionable(self) -> bool:
        """Whether anyone may mention it."""
        ...

    @property
    def hoisted(self) -> bool:
        """Whether its members are listed apart in the member list."""
        ...


class Member(Protocol):
    """A member of the server."""

    @property
    def id(self) -> int:
        """The member's Discord ID."""
        ...

    @property
    def name(self) -> str:
        """Their Discord username."""
        ...

    @property
    def display_name(self) -> str:
        """Their nickname in the server, or their name."""
        ...

    @property
    def mention(self) -> str:
        """The member as a mention, such as `<@123>`."""
        ...

    @property
    def role_ids(self) -> frozenset[int]:
        """The IDs of the roles they hold."""
        ...

    @property
    def roles(self) -> Sequence[Role]:
        """The roles they hold, highest first, without @everyone."""
        ...

    @property
    def top_role(self) -> Role | None:
        """Their highest role, or None when they have none."""
        ...

    @property
    def joined_at(self) -> datetime | None:
        """When they joined the server, when Discord says."""
        ...

    @property
    def avatar_url(self) -> str:
        """Their avatar in this server, or their own."""
        ...

    @property
    def bot(self) -> bool:
        """Whether the member is a bot."""
        ...

    @property
    def timed_out_until(self) -> datetime | None:
        """When their timeout ends, or None when they are not timed out."""
        ...

    async def add_role(self, role: Role, /, *, reason: str | None = None) -> None:
        """Give them the role. Refused for a managed role, @everyone, or a role at or above the bot's own."""
        ...

    async def remove_role(self, role: Role, /, *, reason: str | None = None) -> None:
        """Take the role from them, with the same limits as `add_role`."""
        ...

    async def set_nickname(self, nickname: str | None, /, *, reason: str | None = None) -> None:
        """Set their nickname, or clear it with None. Refused for the owner, or a member whose highest role is at
        or above the bot's."""
        ...

    async def timeout(self, length: timedelta, /, *, reason: str | None = None) -> None:
        """Stop them talking for `length`, up to 28 days, with the same limits as `set_nickname`."""
        ...

    async def remove_timeout(self, *, reason: str | None = None) -> None:
        """End their timeout."""
        ...

    async def kick(self, *, reason: str | None = None) -> None:
        """Remove them from the server. They can join again with an invite."""
        ...

    async def send(
        self,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        files: Sequence["File"] = (),
    ) -> "Message":
        """Send them a direct message. Raises `ActionError` when they do not take messages from this server."""
        ...


@dataclass(frozen=True)
class File:
    """A file to attach to a message.

    - `name` is what it is called in Discord, such as `results.csv`.
    - `data` is its contents.
    """

    name: str
    data: bytes


@dataclass(frozen=True)
class Ban:
    """A ban in the server.

    - `user_id` and `name` are the banned user's ID and Discord username.
    - `reason` is the reason given, if any.
    """

    user_id: int
    name: str
    reason: str | None


class Message(Protocol):
    """A message the bot sent."""

    @property
    def id(self) -> int:
        """The message's Discord ID."""
        ...

    @property
    def channel_id(self) -> int:
        """The ID of the channel it is in."""
        ...

    @property
    def jump_url(self) -> str:
        """A link to the message."""
        ...

    async def edit(
        self,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        buttons: Sequence[Button] = (),
        files: Sequence[File] = (),
    ) -> None:
        """Replace the message's text, embed, buttons and files with these: what is given is what it shows."""
        ...

    async def delete(self) -> None:
        """Delete the message. Deleting one already gone does nothing."""
        ...


class Channel(Protocol):
    """Any channel in the server, to read. Post through `TextChannel`, from `Guild.get_text_channel`."""

    @property
    def id(self) -> int:
        """The channel's Discord ID."""
        ...

    @property
    def name(self) -> str:
        """The channel's name."""
        ...

    @property
    def mention(self) -> str:
        """The channel as a link, such as `<#123>`."""
        ...

    @property
    def kind(self) -> ChannelKind:
        """What sort of channel it is."""
        ...

    @property
    def parent_id(self) -> int | None:
        """Its category, or for a thread the channel it is in; None when it has neither."""
        ...


class TextChannel(Protocol):
    """A channel that takes messages."""

    @property
    def id(self) -> int:
        """The channel's Discord ID."""
        ...

    @property
    def name(self) -> str:
        """The channel's name."""
        ...

    @property
    def mention(self) -> str:
        """The channel as a link, such as `<#123>`."""
        ...

    async def send(
        self,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        ping: Iterable[int] = (),
        files: Sequence[File] = (),
        buttons: Sequence[Button] = (),
    ) -> Message:
        """Post a message. Nobody is mentioned, whatever the text says, except the members whose IDs are in
        `ping`. Up to 25 `buttons` go under it, five to a row. Raises `ActionError` when the bot may not post
        here."""
        ...

    async def get_message(self, message_id: int, /) -> Message | None:
        """One of the bot's own messages in this channel, to edit or delete, or None when it is gone or is not
        the bot's."""
        ...


class Guild(Protocol):
    """The server an action or job is about."""

    @property
    def id(self) -> int:
        """The server's Discord ID."""
        ...

    @property
    def name(self) -> str:
        """The server's name."""
        ...

    @property
    def icon_url(self) -> str | None:
        """The server's icon, or None when it has none."""
        ...

    @property
    def owner_id(self) -> int:
        """The ID of the server's owner."""
        ...

    @property
    def member_count(self) -> int:
        """How many members the server has."""
        ...

    @property
    def roles(self) -> Sequence[Role]:
        """Its roles, highest first, without @everyone."""
        ...

    @property
    def channels(self) -> Sequence[Channel]:
        """Every channel, of every kind."""
        ...

    def get_text_channel(self, channel_id: int, /) -> TextChannel | None:
        """The channel with this ID, or None when there is none, or it takes no messages."""
        ...

    def get_channel(self, channel_id: int, /) -> Channel | None:
        """The channel with this ID, of any kind, or None."""
        ...

    def get_role(self, role_id: int, /) -> Role | None:
        """The role with this ID, or None."""
        ...

    async def get_member(self, user_id: int, /) -> Member | None:
        """The member with this ID, from the cache or else from Discord, or None when they are not in it."""
        ...

    async def find_members(self, prefix: str, /, *, limit: int = 10) -> list[Member]:
        """Members whose name or nickname starts with `prefix`, up to `limit`, at most 100."""
        ...

    async def ban(self, user_id: int, /, *, reason: str | None = None, delete_message_days: int = 0) -> None:
        """Ban a user, whether or not they are still a member, deleting their messages from the last
        `delete_message_days` days, up to 7. Refused for the owner, or a member whose highest role is at or
        above the bot's."""
        ...

    async def unban(self, user_id: int, /, *, reason: str | None = None) -> None:
        """Lift a ban. Raises `ActionError` when the user is not banned."""
        ...

    async def bans(self, *, limit: int = 100) -> list[Ban]:
        """The server's bans, up to `limit`."""
        ...
