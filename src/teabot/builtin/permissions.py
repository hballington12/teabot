"""The admin plugin's permission views: `admin.channels`, every channel's overwrites, and `admin.view_as`, the server as
a set of roles sees it, as Discord's "View server as role" shows. Both are computed from the gateway's cache, with no
request to Discord, and need Manage Server.

Discord's algorithm, for a set of roles, which always includes @everyone:

1. The base is the union of the roles' server permissions. Administrator in it grants everything, everywhere.
2. In a channel, the @everyone overwrite applies, its denies then its allows; then the roles' overwrites together,
   the union of their denies, then the union of their allows. A member's own overwrite would come last; view-as has
   no member.
3. Without View Channel, every other permission in the channel is lost. In a text channel, without Send Messages,
   the permissions that depend on it are lost too.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

import discord
from pydantic import BaseModel, Field

from teabot.sdk import (
    ActionContext,
    ActionError,
    ActionSpec,
    ChannelRef,
    Risk,
    RoleRef,
    Surface,
    UntrustedText,
)

MANAGE_SERVER = discord.Permissions(manage_guild=True)
PAGE = 50
ALL = discord.Permissions.all().value
VIEW = discord.Permissions(view_channel=True).value
# What Send Messages governs in a text channel.
NEEDS_SEND = discord.Permissions(
    embed_links=True, attach_files=True, mention_everyone=True, send_tts_messages=True
).value
TEXT_KINDS = frozenset({"text", "news", "forum", "media"})


# discord.py's names, once each: it lists aliases too, such as manage_permissions for manage_roles. Discord itself calls
# read_messages View Channel.
FLAGS = [
    (name, value)
    for name, value in discord.Permissions.VALID_FLAGS.items()
    if type(discord.Permissions.__dict__[name]).__name__ == "flag_value"
]
PREFERRED = {"read_messages": "view_channel"}


def names(value: int) -> list[str]:
    """A permission value as the names of the permissions it holds."""
    return sorted(PREFERRED.get(name, name) for name, bit in FLAGS if value & bit)


@dataclass(frozen=True)
class Overwrite:
    allow: int
    deny: int


def in_channel(base: int, kind: str, everyone: Overwrite | None, roles: Sequence[Overwrite]) -> int:
    """What a set of roles with server permissions `base` may do in one channel, from its overwrites."""
    if base & discord.Permissions(administrator=True).value:
        return ALL
    value = base
    if everyone is not None:
        value = (value & ~everyone.deny) | everyone.allow
    deny = allow = 0
    for overwrite in roles:
        deny |= overwrite.deny
        allow |= overwrite.allow
    value = (value & ~deny) | allow
    if not value & VIEW:
        return 0
    if kind in TEXT_KINDS and not value & discord.Permissions(send_messages=True).value:
        value &= ~NEEDS_SEND
    return value


class ChannelsQuery(BaseModel):
    page: int = Field(default=1, ge=1, description="Which page of 50 channels, from 1")


class OverwriteInfo(BaseModel):
    target: str = Field(description="The role's or member's ID")
    target_kind: str = Field(description="role or member")
    name: UntrustedText | None
    allow: list[str]
    deny: list[str]


class ChannelPermissions(BaseModel):
    id: ChannelRef
    name: UntrustedText
    kind: str
    category: ChannelRef | None
    synced: bool = Field(description="Whether its overwrites are its category's")
    overwrites: list[OverwriteInfo]


class ChannelsPage(BaseModel):
    channels: list[ChannelPermissions]
    page: int
    pages: int


class ViewAsQuery(BaseModel):
    roles: list[RoleRef] = Field(
        default=[], max_length=10, description="The roles to see the server as, beside @everyone"
    )
    page: int = Field(default=1, ge=1, description="Which page of 50 channels, from 1")


class ChannelView(BaseModel):
    id: ChannelRef
    name: UntrustedText
    kind: str
    category: ChannelRef | None
    visible: bool
    permissions: list[str] = Field(description="What these roles may do there; none when hidden")


class ViewAsPage(BaseModel):
    roles: list[RoleRef]
    server_permissions: list[str]
    administrator: bool
    channels: list[ChannelView]
    page: int
    pages: int


def ordered(guild: discord.Guild) -> list[Any]:
    """Every category and channel in Discord's order: channels without a category first, then each category
    followed by its channels."""
    found: list[Any] = []
    for category, channels in guild.by_category():
        if category is not None:
            found.append(category)
        found.extend(channels)
    return found


def _page[T](items: list[T], page: int) -> tuple[list[T], int]:
    pages = max(1, math.ceil(len(items) / PAGE))
    if page > pages:
        raise ActionError(f"There are only {pages} pages.")
    return items[(page - 1) * PAGE : page * PAGE], pages


def _overwrites(channel: Any, role_ids: frozenset[int]) -> list[OverwriteInfo]:
    found: list[OverwriteInfo] = []
    for target, overwrite in channel.overwrites.items():
        allow, deny = overwrite.pair()
        is_role = target.id in role_ids
        found.append(
            OverwriteInfo(
                target=str(target.id),
                target_kind="role" if is_role else "member",
                name=getattr(target, "name", None),
                allow=names(allow.value),
                deny=names(deny.value),
            )
        )
    return found


def _role_overwrite(channel: Any, role: Any) -> Overwrite | None:
    overwrite = channel.overwrites.get(role)
    if overwrite is None:
        return None
    allow, deny = overwrite.pair()
    return Overwrite(allow.value, deny.value)


def _category_id(channel: Any) -> int | None:
    return channel.category.id if getattr(channel, "category", None) is not None else None


def _roles(guild: discord.Guild, ids: Iterable[int]) -> list[Any]:
    chosen: list[Any] = []
    for role_id in ids:
        role = guild.get_role(role_id)
        if role is None:
            raise ActionError(f"There is no role {role_id} in this server.")
        chosen.append(role)
    return chosen


class Permissions:
    async def channels(self, ctx: ActionContext, data: ChannelsQuery) -> ChannelsPage:
        shown, pages = _page(ordered(ctx.guild), data.page)
        role_ids = frozenset(r.id for r in ctx.guild.roles)
        return ChannelsPage(
            channels=[
                ChannelPermissions(
                    id=c.id,
                    name=c.name,
                    kind=str(c.type),
                    category=_category_id(c),
                    synced=bool(getattr(c, "permissions_synced", False)),
                    overwrites=_overwrites(c, role_ids),
                )
                for c in shown
            ],
            page=data.page,
            pages=pages,
        )

    async def view_as(self, ctx: ActionContext, data: ViewAsQuery) -> ViewAsPage:
        guild = ctx.guild
        everyone = guild.default_role
        roles = [r for r in _roles(guild, data.roles) if r.id != everyone.id]
        base = everyone.permissions.value
        for role in roles:
            base |= role.permissions.value
        shown, pages = _page(ordered(guild), data.page)
        views: list[ChannelView] = []
        for channel in shown:
            overwrites = [o for o in (_role_overwrite(channel, r) for r in roles) if o is not None]
            value = in_channel(base, str(channel.type), _role_overwrite(channel, everyone), overwrites)
            views.append(
                ChannelView(
                    id=channel.id,
                    name=channel.name,
                    kind=str(channel.type),
                    category=_category_id(channel),
                    visible=bool(value & VIEW),
                    permissions=names(value),
                )
            )
        return ViewAsPage(
            roles=[r.id for r in roles],
            server_permissions=names(ALL if base & discord.Permissions(administrator=True).value else base),
            administrator=bool(base & discord.Permissions(administrator=True).value),
            channels=views,
            page=data.page,
            pages=pages,
        )

    def specs(self) -> dict[str, ActionSpec[Any, Any]]:
        table: list[tuple[str, str, type[BaseModel], type[BaseModel], Any]] = [
            (
                "admin.channels",
                "Every channel and category here, with its permission overwrites",
                ChannelsQuery,
                ChannelsPage,
                self.channels,
            ),
            (
                "admin.view_as",
                "The server as a set of roles sees it: each channel, visible or not, and what they may do",
                ViewAsQuery,
                ViewAsPage,
                self.view_as,
            ),
        ]
        return {
            name: ActionSpec(
                name,
                summary,
                inp,
                out,
                Risk.READ,
                run,
                default_permissions=MANAGE_SERVER,
                surfaces=Surface.MCP | Surface.SERVICE,
            )
            for name, summary, inp, out, run in table
        }
