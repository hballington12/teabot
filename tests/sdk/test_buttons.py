"""Buttons on a post, each running a plugin's action as the member who presses it, and posts the bot edits or
deletes afterwards."""

import discord
import pytest
from pydantic import BaseModel

from teabot.adapters.schema import command_group
from teabot.sdk import Button, Context, EmptyConfig, Plugin, Role, Surface, TextChannel
from teabot.sdk.components import BoundAction, parse_custom_id
from teabot.testing import ActionFailed, FakeButton, FakeChannel, HarnessFactory, Refused

plugin = Plugin("pick")
type Ctx = Context[EmptyConfig]


class Posted(BaseModel):
    message: int


@plugin.action(needs="manage_roles")
async def post(ctx: Ctx, channel: TextChannel, role: Role) -> Posted:
    """Post a button for a role.

    Args:
        channel: Where to post
        role: The role the button gives
    """
    sent = await channel.send(
        "Pick a role", buttons=[Button(toggle.bind(role=role), label=role.name, emoji="🗡️", style="primary")]
    )
    return Posted(message=sent.id)


@plugin.action()
async def toggle(ctx: Ctx, role: Role) -> str:
    """Give or take a role.

    Args:
        role: The role
    """
    member = await ctx.guild.get_member(ctx.actor.user_id)
    assert member is not None
    if role.id in member.role_ids:
        await member.remove_role(role)
        return f"{role.name} removed."
    await member.add_role(role)
    return f"You now have {role.name}."


@plugin.action(needs="manage_roles")
async def retitle(ctx: Ctx, channel: TextChannel, message: int, title: str) -> str:
    """Change a post's text and drop its buttons, or delete it when the title is "delete".

    Args:
        channel: The post's channel
        message: The post's ID
        title: Its new text
    """
    found = await channel.get_message(message)
    if found is None:
        return "gone"
    if title == "delete":
        await found.delete()
        return "deleted"
    await found.edit(title)
    return "edited"


async def test_a_press_gives_the_role_and_a_second_press_takes_it(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    raids = harness.guild.add_role("Raids")
    await harness.call(post, channel=channel, role=raids)
    (button,) = channel.sent[0].buttons
    assert (button.label, button.emoji, button.style) == ("Raids", "🗡️", "primary")
    sam = harness.guild.add_member(discord.Permissions.none())
    assert await harness.as_member(sam).press(button) == "You now have Raids."
    assert raids.id in sam.role_ids
    assert await harness.as_member(sam).press(button) == "Raids removed."
    assert raids.id not in sam.role_ids


async def test_a_press_goes_through_the_call_path_with_the_pressers_permissions(
    teabot_harness: HarnessFactory,
) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    mods = harness.guild.add_role("Mods")
    await harness.call(post, channel=channel, role=mods)
    forged = BoundAction("pick.post", {"channel": str(channel.id), "role": str(mods.id)})
    sam = harness.guild.add_member(discord.Permissions.none())
    with pytest.raises(Refused) as caught:
        await harness.as_member(sam).press(FakeButton(None, None, "primary", forged.custom_id()))
    assert caught.value.code == "forbidden"


async def test_a_role_the_bot_cannot_give_is_refused_in_words(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    top = harness.guild.add_role("Top", position=200)
    await harness.call(post, channel=channel, role=top)
    with pytest.raises(ActionFailed) as caught:
        await harness.press(channel.sent[0].buttons[0])
    assert "at or above my highest role" in (caught.value.public_message or "")


async def test_the_bot_edits_and_deletes_its_own_post(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    out = await harness.call(post, channel=channel, role=harness.guild.add_role("Raids"))
    assert await harness.call(retitle, channel=channel, message=out.message, title="Closed") == "edited"
    edited = channel.sent[0]
    assert (edited.content, edited.buttons, edited.edits) == ("Closed", [], 1)
    assert await harness.call(retitle, channel=channel, message=out.message, title="delete") == "deleted"
    assert edited.deleted
    assert await harness.call(retitle, channel=channel, message=out.message, title="again") == "gone"


def test_a_button_holds_its_call_in_its_custom_id() -> None:
    bound = BoundAction("pick.toggle", {"role": "123"})
    assert bound.custom_id() == 'teabot:a:pick.toggle:{"role":"123"}'
    assert parse_custom_id(bound.custom_id()) == bound
    assert parse_custom_id("teabot:core:confirm:abc") is None


def test_a_call_too_long_for_discord_is_refused_when_posted() -> None:
    with pytest.raises(ValueError, match="past Discord's 100"):
        BoundAction("pick.toggle", {"note": "x" * 100}).custom_id()


button_only = Plugin("only")


@button_only.action(surfaces=Surface.COMPONENT)
async def tap(ctx: Ctx) -> str:
    """Tapped."""
    return "tapped"


async def test_a_button_only_action_is_no_command_and_no_tool(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(button_only)
    assert await harness.press(FakeButton("Tap", None, "primary", tap.bind().custom_id())) == "tapped"
    with pytest.raises(Refused) as caught:
        await harness.invoke("only.tap", {})
    assert caught.value.code == "wrong_surface"
    spec = button_only.actions["only.tap"].spec()
    assert command_group("only", [spec])["options"] == [] and Surface.MCP not in spec.surfaces
