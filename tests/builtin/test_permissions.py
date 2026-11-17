"""The permission views: Discord's algorithm for a set of roles, and the overwrites as `admin.channels` lists them."""

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import discord
import pytest

from teabot.builtin.permissions import ChannelsQuery, Overwrite, Permissions, ViewAsQuery, in_channel, names
from teabot.sdk import ActionError

P = discord.Permissions
EVERYONE_ID = 1


@dataclass
class Role:
    id: int
    name: str
    permissions: discord.Permissions

    def __hash__(self) -> int:
        return self.id


@dataclass
class Channel:
    id: int
    name: str
    type: str = "text"
    category: Any = None
    permissions_synced: bool = False
    overwrites: dict[Any, discord.PermissionOverwrite] = field(
        default_factory=dict[Any, discord.PermissionOverwrite]
    )


@dataclass
class Guild:
    roles: list[Role]
    channels: list[Channel]

    @property
    def default_role(self) -> Role:
        return self.roles[0]

    def get_role(self, role_id: int) -> Role | None:
        return next((r for r in self.roles if r.id == role_id), None)

    def by_category(self) -> list[tuple[Any, list[Channel]]]:
        return [(None, self.channels)]


def overwrite(**perms: bool) -> discord.PermissionOverwrite:
    return discord.PermissionOverwrite(**perms)


def server() -> tuple[Guild, Role, Role]:
    everyone = Role(EVERYONE_ID, "@everyone", P(view_channel=True, send_messages=True, embed_links=True))
    staff = Role(2, "Staff", P.none())
    admin = Role(3, "Admins", P(administrator=True))
    general = Channel(10, "general")
    secret = Channel(
        11, "staff", overwrites={everyone: overwrite(view_channel=False), staff: overwrite(view_channel=True)}
    )
    news = Channel(
        12,
        "news",
        overwrites={everyone: overwrite(send_messages=False), staff: overwrite(send_messages=True)},
    )
    return Guild([everyone, staff, admin], [general, secret, news]), everyone, staff


def ctx(guild: Guild) -> Any:
    return SimpleNamespace(guild=guild)


def test_without_view_channel_nothing_else_is_left() -> None:
    assert (
        in_channel(
            P(view_channel=True, send_messages=True).value,
            "text",
            Overwrite(0, P(view_channel=True).value),
            [],
        )
        == 0
    )


def test_without_send_messages_its_dependants_go_in_a_text_channel() -> None:
    value = in_channel(
        P(view_channel=True, send_messages=True, embed_links=True).value,
        "text",
        Overwrite(0, P(send_messages=True).value),
        [],
    )
    assert names(value) == ["view_channel"]


def test_a_roles_allow_beats_the_everyone_deny() -> None:
    value = in_channel(
        P(view_channel=True).value,
        "text",
        Overwrite(0, P(view_channel=True).value),
        [Overwrite(P(view_channel=True).value, 0)],
    )
    assert value & P(view_channel=True).value


def test_administrator_sees_everything() -> None:
    assert in_channel(P(administrator=True).value, "text", Overwrite(0, P.all().value), []) == P.all().value


async def test_view_as_everyone_hides_the_staff_channel_and_mutes_news() -> None:
    guild, _, _ = server()
    page = await Permissions().view_as(ctx(guild), ViewAsQuery())
    seen = {c.name: (c.visible, c.permissions) for c in page.channels}
    assert seen["staff"] == (False, [])
    assert seen["news"] == (True, ["view_channel"])
    assert "send_messages" in seen["general"][1]


async def test_view_as_staff_sees_the_staff_channel_and_can_post_news() -> None:
    guild, _, staff = server()
    page = await Permissions().view_as(ctx(guild), ViewAsQuery(roles=[staff.id]))
    seen = {c.name: c for c in page.channels}
    assert seen["staff"].visible
    assert "send_messages" in seen["news"].permissions and "embed_links" in seen["news"].permissions


async def test_view_as_an_unknown_role_is_refused() -> None:
    guild, _, _ = server()
    with pytest.raises(ActionError):
        await Permissions().view_as(ctx(guild), ViewAsQuery(roles=[999]))


async def test_channels_lists_each_overwrite_by_role() -> None:
    guild, _, _ = server()
    page = await Permissions().channels(ctx(guild), ChannelsQuery())
    secret = next(c for c in page.channels if c.name == "staff")
    assert [(o.target, o.target_kind, o.allow, o.deny) for o in secret.overwrites] == [
        ("1", "role", [], ["view_channel"]),
        ("2", "role", ["view_channel"], []),
    ]
