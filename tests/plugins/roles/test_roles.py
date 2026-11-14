"""teabot-roles: a post of buttons that give members roles, offering only roles that are safe to give out."""

import discord
import pytest

from teabot.plugins.roles import add, delete, list_, plugin, post, remove
from teabot.testing import ActionFailed, FakeChannel, FakeRole, HarnessFactory, PluginHarness, Refused

NONE = discord.Permissions.none()


async def posted(harness: PluginHarness, *roles: FakeRole) -> tuple[FakeChannel, int]:
    channel = harness.guild.add_channel(FakeChannel())
    out = await harness.call(
        post, channel=channel, title="Pick your pings", roles=list(roles), note="Raid pings"
    )
    return channel, out.post


async def test_posting_shows_a_button_for_each_role(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    raids, boss = harness.guild.add_role("Raids"), harness.guild.add_role("Bossing")
    channel, _ = await posted(harness, raids, boss)
    message = channel.sent[0]
    assert message.content == (
        "**Pick your pings**\nRaid pings\nPress a button to take that role, and press it again to give it back."
    )
    assert [b.label for b in message.buttons] == ["Raids", "Bossing"]


async def test_a_press_gives_the_role_and_a_second_press_takes_it_back(
    teabot_harness: HarnessFactory,
) -> None:
    harness = await teabot_harness(plugin)
    raids = harness.guild.add_role("Raids")
    channel, _ = await posted(harness, raids)
    sam = harness.guild.add_member(NONE)
    assert await harness.as_member(sam).press(channel.sent[0].buttons[0]) == "You now have Raids."
    assert raids.id in sam.role_ids
    assert await harness.as_member(sam).press(channel.sent[0].buttons[0]) == "Raids removed."
    assert raids.id not in sam.role_ids


@pytest.mark.parametrize(
    ("make", "says"),
    [
        ("managed", "managed by Discord or an integration"),
        ("moderator", "grants Kick Members"),
        ("above the bot", "at or above my highest role"),
    ],
)
async def test_unsafe_roles_are_refused_when_posted(
    teabot_harness: HarnessFactory, make: str, says: str
) -> None:
    harness = await teabot_harness(plugin)
    role = {
        "managed": lambda: harness.guild.add_role("Booster", managed=True),
        "moderator": lambda: harness.guild.add_role(
            "Mods", permissions=discord.Permissions(kick_members=True)
        ),
        "above the bot": lambda: harness.guild.add_role("Top", position=200),
    }[make]()
    with pytest.raises(ActionFailed) as caught:
        await posted(harness, role)
    assert says in (caught.value.public_message or "")


async def test_an_admin_cannot_offer_a_role_above_their_own(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    helpers = harness.guild.add_role("Helpers")
    vips = harness.guild.add_role("VIPs")
    admin = harness.guild.add_member(discord.Permissions(manage_roles=True), roles=[helpers])
    channel = harness.guild.add_channel(FakeChannel())
    with pytest.raises(ActionFailed) as caught:
        await harness.as_member(admin).call(post, channel=channel, title="Perks", roles=[vips])
    assert caught.value.public_message == "VIPs is at or above your highest role, so you cannot give it out."


async def test_posting_needs_manage_roles(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    with pytest.raises(Refused) as caught:
        await harness.as_member(harness.guild.add_member(NONE)).call(
            post, channel=channel, title="t", roles=[harness.guild.add_role("Raids")]
        )
    assert caught.value.code == "forbidden"


async def test_adding_and_removing_a_role_updates_the_post_in_place(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    raids, boss = harness.guild.add_role("Raids"), harness.guild.add_role("Bossing")
    channel, picker = await posted(harness, raids)
    assert await harness.call(add, post=picker, role=boss) == "Bossing is now on role picker 1."
    assert [b.label for b in channel.sent[0].buttons] == ["Raids", "Bossing"]
    await harness.call(remove, post=picker, role=raids)
    assert [b.label for b in channel.sent[0].buttons] == ["Bossing"]
    assert len(channel.sent) == 1


async def test_a_withdrawn_roles_old_button_says_so(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    raids, boss = harness.guild.add_role("Raids"), harness.guild.add_role("Bossing")
    channel, picker = await posted(harness, raids, boss)
    old = channel.sent[0].buttons[0]
    await harness.call(remove, post=picker, role=raids)
    with pytest.raises(ActionFailed) as caught:
        await harness.as_member(harness.guild.add_member(NONE)).press(old)
    assert caught.value.public_message == "Raids is no longer offered here."


async def test_a_role_made_unsafe_after_posting_stops_working(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    raids = harness.guild.add_role("Raids")
    channel, _ = await posted(harness, raids)
    raids.grants = discord.Permissions(ban_members=True)
    with pytest.raises(ActionFailed, match="grants Ban Members"):
        await harness.as_member(harness.guild.add_member(NONE)).press(channel.sent[0].buttons[0])


async def test_the_list_and_suggestions_name_each_picker(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    await posted(harness, harness.guild.add_role("Raids"))
    (listed,) = await harness.call(list_)
    assert (listed.id, listed.title, listed.roles) == (1, "Pick your pings", 1)
    assert [(c.name, c.value) for c in await harness.autocomplete(add, "post", "ping")] == [
        ("1: Pick your pings", 1)
    ]


async def test_deleting_shows_a_plan_then_removes_the_post(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, picker = await posted(harness, harness.guild.add_role("Raids"))
    plan = await harness.plan(delete, post=picker)
    assert [(e.change, e.target, e.detail) for e in plan.entries] == [
        ("delete", "Pick your pings", "1 roles: Raids")
    ]
    await harness.confirm(plan)
    assert channel.sent[0].deleted
    assert await harness.call(list_) == []
