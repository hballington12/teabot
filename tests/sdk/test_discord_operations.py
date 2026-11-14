"""What plugins can do to a server through the SDK: roles, members, bans and lookups, each refused with a plain
reason where Discord would refuse it, and each carrying a reason for Discord's audit log."""

from datetime import timedelta

import discord
import pytest

from teabot.sdk import ActionError, Context, EmptyConfig, File, Plugin, Role
from teabot.sdk._views import guild_view
from teabot.testing import FakeCategory, FakeChannel, FakeGuild, FakeVoiceChannel, HarnessFactory

NONE = discord.Permissions.none()


def server() -> FakeGuild:
    return FakeGuild()


async def test_a_role_is_given_and_taken_with_a_reason() -> None:
    guild = server()
    raids = guild.add_role("Raids")
    raw = guild.add_member(NONE)
    view = guild_view(guild, "via teabot: roles.toggle, for member 1")
    sam = await view.get_member(raw.id)
    role = view.get_role(raids.id)
    assert sam is not None and role is not None
    await sam.add_role(role)
    assert raw.role_ids == {raids.id}
    await sam.remove_role(role, reason="tidying")
    assert raw.role_ids == frozenset()
    assert raw.reasons == ["via teabot: roles.toggle, for member 1", "tidying"]


@pytest.mark.parametrize(
    ("position", "managed", "says"),
    [(100, False, "at or above my highest role"), (None, True, "managed by Discord or an integration")],
    ids=["above the bot", "managed"],
)
async def test_a_role_the_bot_cannot_manage_is_refused_with_why(
    position: int | None, managed: bool, says: str
) -> None:
    guild = server()
    role_raw = guild.add_role("Special", position=position, managed=managed)
    view = guild_view(guild)
    sam = await view.get_member(guild.add_member(NONE).id)
    role = view.get_role(role_raw.id)
    assert sam is not None and role is not None
    with pytest.raises(ActionError, match=says):
        await sam.add_role(role)


async def test_without_manage_roles_the_bot_says_which_permission_it_needs() -> None:
    guild = server()
    guild.me.guild_permissions = NONE
    raids = guild.add_role("Raids")
    view = guild_view(guild)
    sam, role = await view.get_member(guild.add_member(NONE).id), view.get_role(raids.id)
    assert sam is not None and role is not None
    with pytest.raises(ActionError, match="I need the Manage Roles permission to give or take Raids"):
        await sam.add_role(role)


async def test_nicknames_timeouts_and_kicks_act_on_a_member_below_the_bot() -> None:
    guild = server()
    raw = guild.add_member(NONE, name="sam")
    sam = await guild_view(guild).get_member(raw.id)
    assert sam is not None
    await sam.set_nickname("Samwise")
    await sam.timeout(timedelta(hours=1))
    assert raw.nick == "Samwise" and raw.timed_out_until is not None
    await sam.remove_timeout()
    await sam.kick(reason="spam")
    assert raw.timed_out_until is None and raw.kicked and raw.id not in guild.members
    assert raw.reasons == ["via teabot", "via teabot", "via teabot", "spam"]


async def test_the_owner_and_members_who_outrank_the_bot_are_refused() -> None:
    guild = server()
    owner = guild.add_member(NONE, name="owner")
    guild.owner_id = owner.id
    senior = guild.add_member(NONE, name="senior", roles=[guild.add_role("Admins", position=150)])
    view = guild_view(guild)
    the_owner, the_senior = await view.get_member(owner.id), await view.get_member(senior.id)
    assert the_owner is not None and the_senior is not None
    with pytest.raises(ActionError, match="I cannot kick the server's owner"):
        await the_owner.kick()
    with pytest.raises(
        ActionError, match="senior's highest role is at or above mine, so I cannot time out them"
    ):
        await the_senior.timeout(timedelta(minutes=5))


@pytest.mark.parametrize("length", [timedelta(0), timedelta(days=29)])
async def test_a_timeout_lasts_up_to_28_days(length: timedelta) -> None:
    guild = server()
    sam = await guild_view(guild).get_member(guild.add_member(NONE).id)
    assert sam is not None
    with pytest.raises(ActionError, match="at most 28 days"):
        await sam.timeout(length)


async def test_a_direct_message_is_sent_or_refused_plainly() -> None:
    guild = server()
    raw = guild.add_member(NONE, name="sam")
    sam = await guild_view(guild).get_member(raw.id)
    assert sam is not None
    await sam.send("Welcome!", files=[File("rules.txt", b"Be kind.")])
    assert raw.dms[0].content == "Welcome!" and raw.dms[0].attachments[0].data == b"Be kind."
    raw.dms_closed = True
    with pytest.raises(ActionError, match="sam does not take direct messages from this server"):
        await sam.send("Hello?")


async def test_bans_work_by_user_id_and_list_with_their_reasons() -> None:
    guild = server()
    raw = guild.add_member(NONE, name="sam")
    view = guild_view(guild)
    await view.ban(raw.id, reason="raiding", delete_message_days=1)
    await view.ban(123, reason="alt")
    assert raw.id not in guild.members
    assert {(b.user_id, b.name, b.reason) for b in await view.bans()} == {
        (raw.id, "sam", "raiding"),
        (123, "user", "alt"),
    }
    await view.unban(123)
    with pytest.raises(ActionError, match="That user is not banned here"):
        await view.unban(123)
    with pytest.raises(ActionError, match="up to the last 7 days"):
        await view.ban(456, delete_message_days=8)


async def test_the_server_lists_its_roles_channels_and_members() -> None:
    guild = server()
    low, high = guild.add_role("Low"), guild.add_role("High")
    games = guild.add_channel(FakeCategory(name="games"))
    guild.add_channel(FakeChannel(name="chat", category=games))
    guild.add_channel(FakeVoiceChannel(name="voice"))
    guild.add_member(NONE, name="sam")
    guild.add_member(NONE, name="sally")
    view = guild_view(guild)
    assert [r.name for r in view.roles] == ["High", "Low"]
    assert (high.position, low.position) == (2, 1)
    assert sorted((c.name, c.kind, c.parent_id) for c in view.channels) == [
        ("chat", "text", games.id),
        ("games", "category", None),
        ("voice", "voice", None),
    ]
    assert sorted(m.name for m in await view.find_members("sa")) == ["sally", "sam"]
    assert (view.member_count, view.icon_url) == (2, None)


async def test_a_role_shows_what_it_grants() -> None:
    guild = server()
    mods = guild.add_role("Mods", permissions=discord.Permissions(kick_members=True, manage_messages=True))
    role = guild_view(guild).get_role(mods.id)
    assert role is not None
    assert role.permissions == {"kick_members", "manage_messages"}
    assert (role.managed, role.mentionable, role.hoisted, role.colour) == (False, False, False, 0)


plugin = Plugin("give")


@plugin.action(needs="manage_roles")
async def give(ctx: Context[EmptyConfig], role: Role) -> str:
    """Give the caller a role.

    Args:
        role: The role to give
    """
    member = await ctx.guild.get_member(ctx.actor.user_id)
    assert member is not None
    await member.add_role(role)
    return "done"


async def test_a_plugins_change_tells_discord_which_action_made_it(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    raids = harness.guild.add_role("Raids")
    await harness.call(give, role=raids)
    assert harness.member.reasons == [f"via teabot: give.give, for member {harness.member.id}"]
