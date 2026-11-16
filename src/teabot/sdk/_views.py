"""The SDK's Discord types (`teabot.sdk.guild`) over discord.py's objects. Internal to the SDK.

The views read and call only discord.py's own attributes and methods, which `teabot.testing`'s fakes share, so one
implementation serves Discord and tests alike. They are the only Discord objects plugin code receives.

Each operation acts as the bot. It first checks what Discord would refuse, from the bot's highest role and its
permissions, and raises `ActionError` with the reason; a refusal Discord gives anyway becomes one too.
"""

import io
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

import discord

from teabot.sdk.actions import ActionError
from teabot.sdk.components import BUTTONS_BESIDE_SELECT, BUTTONS_MAX, Button, Select
from teabot.sdk.guild import (
    Attachment,
    Ban,
    Channel,
    ChannelKind,
    File,
    Guild,
    Member,
    Message,
    ReceivedMessage,
    Role,
    TextChannel,
)
from teabot.sdk.permissions import Permission

FORBIDDEN = "I am not allowed to post in that channel."
DEFAULT_REASON = "via teabot"
MAX_TIMEOUT = timedelta(days=28)
KINDS: dict[str, ChannelKind] = {
    "text": "text",
    "voice": "voice",
    "category": "category",
    "forum": "forum",
    "stage_voice": "stage",
    "news": "announcement",
    "public_thread": "thread",
    "private_thread": "thread",
    "news_thread": "thread",
}


def _words(permission: str) -> str:
    """`manage_roles` as Discord writes it: Manage Roles."""
    return permission.replace("_", " ").title()


def _top_position(member: Any, guild: Any) -> int:
    positions = [int(r.position) for r in getattr(member, "roles", ()) if int(r.id) != int(guild.id)]
    return max(positions, default=0)


def _require(guild: Any, permission: str, doing: str) -> None:
    """Refuse unless the bot holds `permission` in the server."""
    held = guild.me.guild_permissions
    if not (held.administrator or getattr(held, permission)):
        raise ActionError(f"I need the {_words(permission)} permission to {doing}.")


def _files(files: Sequence[File]) -> list[discord.File]:
    return [discord.File(io.BytesIO(f.data), filename=f.name) for f in files]


STYLES = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}


DEFAULT_KINDS = {
    "role": discord.SelectDefaultValueType.role,
    "channel": discord.SelectDefaultValueType.channel,
    "member": discord.SelectDefaultValueType.user,
}


def _menu(select: Select) -> discord.ui.Item[Any]:
    custom_id = select.bound.custom_id(select.into)
    limits: dict[str, Any] = {
        "custom_id": custom_id,
        "placeholder": select.placeholder,
        "min_values": select.min,
        "max_values": select.max,
    }
    if select.kind != "options" and select.defaults:
        kind = DEFAULT_KINDS[select.kind]
        limits["default_values"] = [discord.SelectDefaultValue(id=i, type=kind) for i in select.defaults]
    if select.kind == "role":
        return discord.ui.RoleSelect(**limits)
    if select.kind == "channel":
        return discord.ui.ChannelSelect(**limits)
    if select.kind == "member":
        return discord.ui.UserSelect(**limits)
    options = [
        discord.SelectOption(
            label=o.label, value=o.value, emoji=o.emoji, description=o.description, default=o.default
        )
        for o in select.options
    ]
    return discord.ui.Select(options=options, **limits)


def _components(buttons: Sequence[Button], select: Select | None = None) -> discord.ui.View | None:
    """discord.py's form of the buttons, five to a row, and of a select menu, which takes a row of its own. A press
    or a choice reaches the interaction router by its custom id, so the view is only ever a carrier and never
    waits for them itself."""
    if not buttons and select is None:
        return None
    room = BUTTONS_MAX if select is None else BUTTONS_BESIDE_SELECT
    if len(buttons) > room:
        raise ValueError(f"A post holds at most {room} buttons here, not {len(buttons)}.")
    view = discord.ui.View(timeout=None)
    if select is not None:
        view.add_item(_menu(select))
    for button in buttons:
        view.add_item(
            discord.ui.Button(
                label=button.label,
                emoji=button.emoji,
                style=STYLES[button.style],
                custom_id=button.bound.custom_id(),
            )
        )
    view.stop()
    return view


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

    @property
    def position(self) -> int:
        return int(self.raw.position)

    @property
    def permissions(self) -> frozenset[Permission]:
        granted = self.raw.permissions
        if isinstance(granted, discord.Permissions):
            return frozenset(cast(Permission, name) for name, on in granted if on)
        return frozenset(granted)

    @property
    def colour(self) -> int:
        colour = self.raw.colour
        return int(getattr(colour, "value", colour))

    @property
    def managed(self) -> bool:
        return bool(self.raw.managed)

    @property
    def mentionable(self) -> bool:
        return bool(self.raw.mentionable)

    @property
    def hoisted(self) -> bool:
        return bool(self.raw.hoist)


def _roles(raw_roles: Iterable[Any], guild: Any) -> list[Role]:
    """Highest first, without @everyone, whose ID is the server's."""
    kept = [r for r in raw_roles if int(r.id) != int(guild.id)]
    return [RoleView(r) for r in sorted(kept, key=lambda r: int(r.position), reverse=True)]


@dataclass(frozen=True)
class MemberView:
    raw: Any
    guild: Any
    reason: str = DEFAULT_REASON

    @property
    def id(self) -> int:
        return int(self.raw.id)

    @property
    def name(self) -> str:
        return str(self.raw.name)

    @property
    def display_name(self) -> str:
        return str(self.raw.display_name)

    @property
    def mention(self) -> str:
        return f"<@{self.id}>"

    @property
    def role_ids(self) -> frozenset[int]:
        return frozenset(int(role.id) for role in getattr(self.raw, "roles", ()))

    @property
    def roles(self) -> Sequence[Role]:
        return _roles(getattr(self.raw, "roles", ()), self.guild)

    @property
    def top_role(self) -> Role | None:
        roles = self.roles
        return roles[0] if roles else None

    @property
    def joined_at(self) -> datetime | None:
        return self.raw.joined_at

    @property
    def avatar_url(self) -> str:
        return str(self.raw.display_avatar.url)

    @property
    def bot(self) -> bool:
        return bool(self.raw.bot)

    @property
    def timed_out_until(self) -> datetime | None:
        return self.raw.timed_out_until

    def _role_to_change(self, role: Role) -> Any:
        found = self.guild.get_role(role.id)
        if found is None:
            raise ActionError("That role is not in this server.")
        if int(found.id) == int(self.guild.id):
            raise ActionError("Everyone has @everyone; it cannot be given or taken.")
        if found.managed:
            raise ActionError(
                f"{found.name} is managed by Discord or an integration, so nobody can give or take it."
            )
        if int(found.position) >= _top_position(self.guild.me, self.guild):
            raise ActionError(
                f"{found.name} is at or above my highest role, so I cannot give or take it. "
                "Move my role above it in Server Settings, then Roles."
            )
        _require(self.guild, "manage_roles", f"give or take {found.name}")
        return found

    def check_outranked(self, doing: str, permission: str) -> None:
        if self.id == int(self.guild.owner_id):
            raise ActionError(f"I cannot {doing} the server's owner.")
        if _top_position(self.raw, self.guild) >= _top_position(self.guild.me, self.guild):
            raise ActionError(
                f"{self.display_name}'s highest role is at or above mine, so I cannot {doing} them."
            )
        _require(self.guild, permission, f"{doing} members")

    async def _call(self, doing: str, call: Any) -> None:
        try:
            await call
        except discord.Forbidden:
            raise ActionError(f"Discord would not let me {doing}.") from None

    async def add_role(self, role: Role, /, *, reason: str | None = None) -> None:
        found = self._role_to_change(role)
        await self._call(f"give {found.name}", self.raw.add_roles(found, reason=reason or self.reason))

    async def remove_role(self, role: Role, /, *, reason: str | None = None) -> None:
        found = self._role_to_change(role)
        await self._call(f"take {found.name}", self.raw.remove_roles(found, reason=reason or self.reason))

    async def set_nickname(self, nickname: str | None, /, *, reason: str | None = None) -> None:
        if nickname is not None and not 1 <= len(nickname) <= 32:
            raise ActionError("A nickname is 1 to 32 characters.")
        self.check_outranked("rename", "manage_nicknames")
        await self._call("rename them", self.raw.edit(nick=nickname, reason=reason or self.reason))

    async def timeout(self, length: timedelta, /, *, reason: str | None = None) -> None:
        if not timedelta(0) < length <= MAX_TIMEOUT:
            raise ActionError("A timeout lasts more than no time, and at most 28 days.")
        self.check_outranked("time out", "moderate_members")
        await self._call("time them out", self.raw.timeout(length, reason=reason or self.reason))

    async def remove_timeout(self, *, reason: str | None = None) -> None:
        self.check_outranked("end the timeout of", "moderate_members")
        await self._call("end their timeout", self.raw.timeout(None, reason=reason or self.reason))

    async def kick(self, *, reason: str | None = None) -> None:
        self.check_outranked("kick", "kick_members")
        await self._call("kick them", self.raw.kick(reason=reason or self.reason))

    async def send(
        self, content: str | None = None, *, embed: discord.Embed | None = None, files: Sequence[File] = ()
    ) -> Message:
        try:
            sent = await self.raw.send(
                content, embed=embed, files=_files(files), allowed_mentions=allowed_mentions(())
            )
        except discord.Forbidden:
            raise ActionError(
                f"{self.display_name} does not take direct messages from this server."
            ) from None
        return MessageView(sent)


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

    async def edit(
        self,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        buttons: Sequence[Button] = (),
        files: Sequence[File] = (),
        select: Select | None = None,
    ) -> None:
        try:
            await self.raw.edit(
                content=content,
                embed=embed,
                view=_components(buttons, select),
                attachments=_files(files),
                allowed_mentions=allowed_mentions(()),
            )
        except discord.NotFound:
            raise ActionError("That message has been deleted.") from None
        except discord.Forbidden:
            raise ActionError("Discord would not let me edit that message.") from None

    async def delete(self) -> None:
        try:
            await self.raw.delete()
        except discord.NotFound:
            return
        except discord.Forbidden:
            raise ActionError("Discord would not let me delete that message.") from None


def allowed_mentions(ping: Iterable[int]) -> discord.AllowedMentions:
    """Nobody is mentioned except the members named, whatever the text says."""
    users = [discord.Object(id=user_id) for user_id in ping]
    return discord.AllowedMentions(everyone=False, users=users, roles=False, replied_user=False)


@dataclass(frozen=True)
class TextChannelView:
    raw: Any
    guild: Any = None

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
        self,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        ping: Iterable[int] = (),
        files: Sequence[File] = (),
        buttons: Sequence[Button] = (),
        select: Select | None = None,
    ) -> Message:
        extra: dict[str, Any] = {}
        view = _components(buttons, select)
        if view is not None:
            extra["view"] = view
        try:
            sent = await self.raw.send(
                content, embed=embed, allowed_mentions=allowed_mentions(ping), files=_files(files), **extra
            )
        except discord.Forbidden:
            raise ActionError(FORBIDDEN) from None
        return MessageView(sent)

    async def get_message(self, message_id: int, /) -> Message | None:
        try:
            found = await self.raw.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden):
            return None
        me = getattr(self.guild, "me", None)
        if me is not None and int(found.author.id) != int(me.id):
            return None
        return MessageView(found)

    async def read_message(self, message_id: int, /) -> ReceivedMessage | None:
        try:
            found = await self.raw.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden):
            return None
        return ReceivedMessage(
            int(found.id),
            self.id,
            int(found.author.id),
            str(found.content or ""),
            tuple(Attachment(**a) for a in attachments(found)),
        )

    async def reactors(self, message_id: int, emoji: str, /) -> tuple[int, ...]:
        try:
            found = await self.raw.fetch_message(message_id)
        except (discord.NotFound, discord.Forbidden):
            return ()
        reaction = next((r for r in found.reactions if str(r.emoji) == emoji), None)
        if reaction is None:
            return ()
        return tuple([int(user.id) async for user in reaction.users() if not user.bot])


def attachments(message: Any) -> list[dict[str, str]]:
    """A message's files as `Attachment`'s fields, which an event's job payload carries as they are."""
    return [
        {"filename": str(a.filename), "url": str(a.url), "content_type": str(a.content_type or "")}
        for a in message.attachments
    ]


def _kind(channel: Any) -> str:
    """The fakes name their kind; discord.py gives a `ChannelType`."""
    kind = getattr(channel, "type", None)
    return str(getattr(kind, "name", kind))


def takes_messages(channel: Any) -> bool:
    """A text channel, thread or voice chat, rather than a category or forum, which have no `send`."""
    return channel is not None and callable(getattr(channel, "send", None)) and _kind(channel) != "voice"


@dataclass(frozen=True)
class ChannelView:
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

    @property
    def kind(self) -> ChannelKind:
        return KINDS.get(_kind(self.raw), "other")

    @property
    def parent_id(self) -> int | None:
        parent = getattr(self.raw, "parent_id", None) or getattr(self.raw, "category_id", None)
        return int(parent) if parent is not None else None

    @property
    def nsfw(self) -> bool:
        # discord.py's channels and threads say through is_nsfw(), which for a thread asks its channel.
        is_nsfw = getattr(self.raw, "is_nsfw", None)
        return bool(is_nsfw()) if callable(is_nsfw) else False


@dataclass(frozen=True)
class GuildView:
    raw: Any
    reason: str = DEFAULT_REASON

    @property
    def id(self) -> int:
        return int(self.raw.id)

    @property
    def name(self) -> str:
        return str(getattr(self.raw, "name", ""))

    @property
    def icon_url(self) -> str | None:
        icon = getattr(self.raw, "icon", None)
        return str(icon.url) if icon is not None else None

    @property
    def owner_id(self) -> int:
        return int(self.raw.owner_id)

    @property
    def member_count(self) -> int:
        return int(self.raw.member_count or 0)

    @property
    def me(self) -> Member:
        return self._member(self.raw.me)

    @property
    def roles(self) -> Sequence[Role]:
        return _roles(self.raw.roles, self.raw)

    @property
    def channels(self) -> Sequence[Channel]:
        return [ChannelView(c) for c in self.raw.channels]

    def _find_channel(self, channel_id: int) -> Any:
        """A channel or a thread: discord.py's `get_channel` leaves threads out."""
        find = getattr(self.raw, "get_channel_or_thread", None) or self.raw.get_channel
        return find(channel_id)

    def get_text_channel(self, channel_id: int, /) -> TextChannel | None:
        channel = self._find_channel(channel_id)
        return TextChannelView(channel, self.raw) if takes_messages(channel) else None

    def get_channel(self, channel_id: int, /) -> Channel | None:
        channel = self._find_channel(channel_id)
        return ChannelView(channel) if channel is not None else None

    def get_role(self, role_id: int, /) -> Role | None:
        role = self.raw.get_role(role_id)
        return RoleView(role) if role is not None else None

    def _member(self, raw: Any) -> Member:
        return MemberView(raw, self.raw, self.reason)

    async def get_member(self, user_id: int, /) -> Member | None:
        member = self.raw.get_member(user_id)
        if member is None:
            try:
                member = await self.raw.fetch_member(user_id)
            except discord.NotFound:
                return None
        return self._member(member)

    async def find_members(self, prefix: str, /, *, limit: int = 10) -> list[Member]:
        found = await self.raw.query_members(prefix, limit=max(1, min(limit, 100)))
        return [self._member(m) for m in found]

    async def ban(self, user_id: int, /, *, reason: str | None = None, delete_message_days: int = 0) -> None:
        if not 0 <= delete_message_days <= 7:
            raise ActionError("A ban deletes messages from up to the last 7 days.")
        member = self.raw.get_member(user_id)
        if member is not None:
            MemberView(member, self.raw).check_outranked("ban", "ban_members")
        elif user_id == int(self.raw.owner_id):
            raise ActionError("I cannot ban the server's owner.")
        else:
            _require(self.raw, "ban_members", "ban members")
        try:
            await self.raw.ban(
                discord.Object(id=user_id),
                reason=reason or self.reason,
                delete_message_seconds=delete_message_days * 86400,
            )
        except discord.NotFound:
            raise ActionError("There is no Discord user with that ID.") from None
        except discord.Forbidden:
            raise ActionError("Discord would not let me ban them.") from None

    async def unban(self, user_id: int, /, *, reason: str | None = None) -> None:
        _require(self.raw, "ban_members", "lift bans")
        try:
            await self.raw.unban(discord.Object(id=user_id), reason=reason or self.reason)
        except discord.NotFound:
            raise ActionError("That user is not banned here.") from None

    async def bans(self, *, limit: int = 100) -> list[Ban]:
        _require(self.raw, "ban_members", "see the bans")
        return [Ban(int(e.user.id), str(e.user.name), e.reason) async for e in self.raw.bans(limit=limit)]


def guild_view(guild: Any, reason: str = DEFAULT_REASON) -> Guild:
    """The SDK's view of a server, for plugin code: discord.py's `Guild`, or a `teabot.testing` fake. `reason` goes
    to Discord's audit log with every change the plugin makes without its own."""
    return GuildView(guild, reason)
