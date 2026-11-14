"""The SDK's Discord types (`teabot.sdk.guild`) over discord.py's objects. Internal to the SDK.

The views read only discord.py's own attributes, which `teabot.testing`'s fakes share, so one implementation
serves Discord and tests alike. They are the only Discord objects plugin code receives.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import discord

from teabot.sdk.actions import ActionError
from teabot.sdk.guild import Guild, Member, Message, Role, TextChannel

FORBIDDEN = "I am not allowed to post in that channel."


@dataclass(frozen=True)
class RoleView:
    raw: Any

    @property
    def id(self) -> int:
        return int(self.raw.id)

    @property
    def name(self) -> str:
        return str(self.raw.name)

    @property
    def mention(self) -> str:
        return f"<@&{self.id}>"


@dataclass(frozen=True)
class MemberView:
    raw: Any

    @property
    def id(self) -> int:
        return int(self.raw.id)

    @property
    def display_name(self) -> str:
        return str(self.raw.display_name)

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    @property
    def role_ids(self) -> frozenset[int]:
        return frozenset(int(role.id) for role in getattr(self.raw, "roles", ()))


@dataclass(frozen=True)
class MessageView:
    raw: Any

    @property
    def id(self) -> int:
        return int(self.raw.id)

    @property
    def channel_id(self) -> int:
        channel = getattr(self.raw, "channel", None)
        return int(channel.id) if channel is not None else int(self.raw.channel_id)

    @property
    def jump_url(self) -> str:
        return str(self.raw.jump_url)


def allowed_mentions(ping: Iterable[int]) -> discord.AllowedMentions:
    """Nobody is mentioned except the members named, whatever the text says."""
    users = [discord.Object(id=user_id) for user_id in ping]
    return discord.AllowedMentions(everyone=False, users=users, roles=False, replied_user=False)


@dataclass(frozen=True)
class TextChannelView:
    raw: Any

    @property
    def id(self) -> int:
        return int(self.raw.id)

    @property
    def name(self) -> str:
        return str(self.raw.name)

    @property
    def mention(self) -> str:
        return f"<#{self.id}>"

    async def send(
        self, content: str | None = None, *, embed: discord.Embed | None = None, ping: Iterable[int] = ()
    ) -> Message:
        try:
            sent = await self.raw.send(content, embed=embed, allowed_mentions=allowed_mentions(ping))
        except discord.Forbidden:
            raise ActionError(FORBIDDEN) from None
        return MessageView(sent)


def takes_messages(channel: Any) -> bool:
    """A text channel, thread or voice chat, rather than a category or forum, which have no `send`."""
    return channel is not None and callable(getattr(channel, "send", None)) and _kind(channel) != "voice"


def _kind(channel: Any) -> str:
    """The fakes name their kind; discord.py's voice channels can take messages, but plugins mean text."""
    kind = getattr(channel, "type", None)
    return str(getattr(kind, "name", kind))


@dataclass(frozen=True)
class GuildView:
    raw: Any

    @property
    def id(self) -> int:
        return int(self.raw.id)

    @property
    def name(self) -> str:
        return str(getattr(self.raw, "name", ""))

    def get_text_channel(self, channel_id: int, /) -> TextChannel | None:
        channel = self.raw.get_channel(channel_id)
        return TextChannelView(channel) if takes_messages(channel) else None

    def get_role(self, role_id: int, /) -> Role | None:
        role = self.raw.get_role(role_id)
        return RoleView(role) if role is not None else None

    async def get_member(self, user_id: int, /) -> Member | None:
        member = self.raw.get_member(user_id)
        if member is None:
            try:
                member = await self.raw.fetch_member(user_id)
            except discord.NotFound:
                return None
        return MemberView(member)


def guild_view(guild: discord.Guild) -> Guild:
    """The SDK's view of a server, for plugin code."""
    return GuildView(guild)
