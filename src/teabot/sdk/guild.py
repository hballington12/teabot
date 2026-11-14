"""The parts of a Discord server a plugin works with (D45). The core gives plugins these, never discord.py's own
objects, so plugin code types the same against Discord and against `teabot.testing`'s fakes.

- `Guild`: the server, to find its channels, roles and members.
- `TextChannel`: a channel that takes messages. Its `send` mentions nobody unless `ping` names them.
- `Member`, `Role` and `Message`: what those lookups and sends return.
"""

from collections.abc import Iterable
from typing import Protocol

import discord


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


class Member(Protocol):
    """A member of the server."""

    @property
    def id(self) -> int:
        """The member's Discord ID."""
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
        self, content: str | None = None, *, embed: discord.Embed | None = None, ping: Iterable[int] = ()
    ) -> Message:
        """Post a message. Nobody is mentioned, whatever the text says, except the members whose IDs are in
        `ping`. Raises `ActionError` when the bot may not post here."""
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

    def get_text_channel(self, channel_id: int, /) -> TextChannel | None:
        """The channel with this ID, or None when there is none, or it takes no messages."""
        ...

    def get_role(self, role_id: int, /) -> Role | None:
        """The role with this ID, or None."""
        ...

    async def get_member(self, user_id: int, /) -> Member | None:
        """The member with this ID, from the cache or else from Discord, or None when they are not in it."""
        ...
