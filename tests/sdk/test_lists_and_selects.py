"""List inputs, which Discord shows as numbered options and MCP as an array, and select menus, which fill one."""

from typing import Annotated

import discord
import pytest
from pydantic import Field

from teabot.adapters.schema import fold_lists, mcp_input_schema, slash_fields
from teabot.sdk import Choice, Context, EmptyConfig, Option, Plugin, Role, Select, TextChannel
from teabot.sdk._signature import SignatureError
from teabot.testing import FakeChannel, HarnessFactory

plugin = Plugin("lists")
type Ctx = Context[EmptyConfig]
type Picked = Annotated[list[Role], Field(min_length=1, max_length=3)]
type Tags = Annotated[list[str], Field(max_length=5)]


@plugin.action()
async def name_roles(ctx: Ctx, roles: Picked) -> str:
    """Name some roles.

    Args:
        roles: The roles
    """
    return ", ".join(r.name for r in roles)


@plugin.action()
async def menu(ctx: Ctx, channel: TextChannel) -> str:
    """Post a menu of tags and a role picker.

    Args:
        channel: Where to post
    """
    tags = Select(
        tag.bind(prefix="#"),
        into="chosen",
        options=(Option("Raids", "raids"), Option("Bossing", "boss")),
        max=2,
    )
    await channel.send("Tags", select=tags)
    await channel.send("Roles", select=Select(pick.bind(), into="roles", kind="role", max=3))
    return "posted"


@plugin.action()
async def tag(ctx: Ctx, prefix: str, chosen: Tags | None = None) -> str:
    """Show the chosen tags.

    Args:
        prefix: Put before each tag
        chosen: The tags chosen
    """
    return " ".join(prefix + c for c in chosen or [])


@plugin.action()
async def pick(ctx: Ctx, roles: Annotated[list[Role], Field(max_length=3)] | None = None) -> str:
    """Show the chosen roles.

    Args:
        roles: The roles chosen
    """
    return ", ".join(r.name for r in roles or []) or "none"


def test_a_list_is_numbered_options_on_discord_and_an_array_over_mcp() -> None:
    spec = plugin.actions["lists.name_roles"].spec()
    options = slash_fields(spec.input).options
    assert [(o["name"], o["type"], o["required"]) for o in options] == [
        ("roles_1", 8, True),
        ("roles_2", 8, False),
        ("roles_3", 8, False),
    ]
    assert mcp_input_schema(spec)["properties"]["roles"]["type"] == "array"
    assert fold_lists(spec.input, {"roles_1": "1", "roles_3": "3"}) == {"roles": ["1", "3"]}


async def test_a_list_of_roles_arrives_as_the_roles(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    raids, boss = harness.guild.add_role("Raids"), harness.guild.add_role("Bossing")
    assert await harness.call(name_roles, roles=[raids, boss]) == "Raids, Bossing"


async def test_a_menu_of_options_fills_its_list_with_the_values_chosen(
    teabot_harness: HarnessFactory,
) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    await harness.call(menu, channel=channel)
    select = channel.sent[0].select
    assert select is not None and (select.kind, select.options, select.max) == (
        "options",
        ["raids", "boss"],
        2,
    )
    member = harness.guild.add_member(discord.Permissions.none())
    assert await harness.as_member(member).choose(select, ["raids", "boss"]) == "#raids #boss"


async def test_a_role_picker_fills_its_list_with_the_roles_chosen(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    raids = harness.guild.add_role("Raids")
    await harness.call(menu, channel=channel)
    select = channel.sent[1].select
    assert select is not None and select.kind == "role"
    assert await harness.choose(select, [raids]) == "Raids"
    assert await harness.choose(select, []) == "none"


def test_a_list_without_a_limit_is_refused_when_the_action_is_set_up() -> None:
    bad = Plugin("bad")

    @bad.action()
    async def many(ctx: Ctx, roles: list[Role]) -> str:
        """Too many.

        Args:
            roles: The roles
        """
        return ""

    with pytest.raises((SignatureError, ValueError), match="a list needs Field"):
        bad.actions["bad.many"].spec()


picker = Plugin("suggest")
type PCtx = Context[EmptyConfig]


@picker.action(needs="manage_guild")
async def find(ctx: PCtx, name: str) -> str:
    """Find a thing.

    Args:
        name: The thing's name
    """
    return name


@find.autocomplete("name")
async def names(ctx: PCtx, typed: str) -> list[Choice[str]]:
    if typed == "boom":
        raise RuntimeError("the suggester broke")
    return [Choice(n, n) for n in ("raids", "bossing", "rares") if n.startswith(typed)]


async def test_an_option_suggests_values_as_the_member_types(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(picker)
    spec = picker.actions["suggest.find"].spec()
    assert slash_fields(spec.input, spec.suggest).options[0]["autocomplete"] is True
    assert [c.value for c in await harness.autocomplete(find, "name", "ra")] == ["raids", "rares"]
    assert await harness.autocomplete(find, "name", "boom") == []


async def test_a_member_who_may_not_run_the_action_gets_no_suggestions(
    teabot_harness: HarnessFactory,
) -> None:
    harness = await teabot_harness(picker)
    member = harness.guild.add_member(discord.Permissions.none())
    found = await harness.registry.suggest("suggest.find", harness.guild.id, member.id, "name", "ra")
    assert found == []


def test_suggestions_are_for_options_the_action_has() -> None:
    with pytest.raises(SignatureError, match="has no option nope"):
        find.autocomplete("nope")
