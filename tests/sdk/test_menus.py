"""Right-click commands on members and messages run their actions with the target."""

import discord
import pytest

from teabot.adapters.schema import commands_for
from teabot.core.registry import ActionSource
from teabot.sdk import Context, EmptyConfig, Member, Plugin, ReceivedMessage, Surface
from teabot.sdk._signature import SignatureError
from teabot.testing import HarnessFactory
from teabot.testing.fakes import FakeChannel

plugin = Plugin("menus")
type Ctx = Context[EmptyConfig]


@plugin.action(menu="Give a pet", needs="manage_roles")
async def give_pet(ctx: Ctx, member: Member) -> str:
    """Give a member a pet.

    Args:
        member: Who gets it.
    """
    return f"{member.display_name} gets a pet"


@plugin.action(menu="Report")
async def report(ctx: Ctx, message: ReceivedMessage) -> str:
    """Report a message.

    Args:
        message: The message.
    """
    return f"reported {message.id}: {message.content}"


def test_a_menu_on_a_message_is_no_slash_command_and_both_are_right_click_commands() -> None:
    assert Surface.SLASH not in report.spec().surfaces
    assert Surface.SLASH in give_pet.spec().surfaces
    source = ActionSource(EmptyConfig, {a.name: a.spec() for a in plugin.actions.values()})
    commands = commands_for({"menus": source})
    menus = [c for c in commands if c["type"] in (2, 3)]
    assert menus == [
        {
            "type": 2,
            "name": "Give a pet",
            "default_member_permissions": str(discord.Permissions(manage_roles=True).value),
        },
        {"type": 3, "name": "Report"},
    ]


async def test_the_target_reaches_the_action(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    member = harness.guild.add_member(discord.Permissions.none(), name="zezima")
    assert await harness.menu(give_pet, member) == "zezima gets a pet"
    channel = harness.guild.add_channel(FakeChannel())
    posted = await harness.post(channel, member, "spam")
    assert await harness.menu(report, posted) == f"reported {posted.id}: spam"


def test_a_menu_takes_one_member_or_message() -> None:
    other = Plugin("menus2")

    async def two(ctx: Context[EmptyConfig], member: Member, note: str) -> str:
        """Two inputs.

        Args:
            member: Who.
            note: Why.
        """
        return note

    with pytest.raises(SignatureError, match="takes one input"):
        other.action(menu="Two")(two)
