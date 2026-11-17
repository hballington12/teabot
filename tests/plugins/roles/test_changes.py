"""Role changes for members (role-changes.md): named changes inside the apply, matching changes as a paced job
that checks its grant and each member again, and following, stopping and reverting them."""

import json
from typing import Any

import discord

from teabot.core.plans import Planned
from teabot.core.registry import Call
from teabot.plugins.roles import plugin
from teabot.plugins.roles.changes import give, take
from teabot.sdk import Actor
from teabot.testing import FakeMember, FakeRole, HarnessFactory, PluginHarness

ADMIN = discord.Permissions(manage_roles=True, manage_guild=True)
NONE = discord.Permissions.none()


async def server(teabot_harness: HarnessFactory) -> tuple[PluginHarness, FakeRole, FakeRole]:
    """The first member is a moderator ranked above Friends and Clan Member, with Manage Roles and Manage Server."""
    harness = await teabot_harness(plugin)
    friends = harness.guild.add_role("Friends", position=2)
    clan = harness.guild.add_role("Clan Member", position=3)
    mod = harness.guild.add_role("Mod", position=10)
    harness.member.guild_permissions = ADMIN
    harness.member.roles = [mod]
    return harness, friends, clan


async def directory(harness: PluginHarness, members: list[FakeMember]) -> None:
    """The directory's copy of the server: these members, with their roles as they are now."""
    db: Any = harness.admin
    await db.execute(
        "INSERT INTO core.directory_state (guild_id, backfilled) VALUES ($1, true)", harness.guild.id
    )
    for m in members:
        await db.execute(
            "INSERT INTO core.members (guild_id, user_id, name, role_ids, observed_at) VALUES ($1, $2, $3, $4, now())",
            harness.guild.id,
            m.id,
            m.name,
            [r.id for r in m.roles],
        )


async def call(harness: PluginHarness, action: str, raw: dict[str, Any], via: str = "mcp") -> Any:
    actor = Actor(harness.member.id, via, None)  # pyright: ignore[reportArgumentType]
    return await harness.registry.invoke(Call(action, harness.guild.id, actor, raw))


async def confirmed(harness: PluginHarness, action: str, raw: dict[str, Any]) -> None:
    plan = await call(harness, action, raw)
    assert isinstance(plan, Planned)
    await call(harness, action, raw | {"confirm": plan.confirm})
    await finish(harness)


async def finish(harness: PluginHarness) -> None:
    """Run the change's bursts to the end, ten seconds apart, as the queue would."""
    for _ in range(10):
        await harness.run_jobs()
        await harness.advance(seconds=11)
    await harness.run_jobs()


async def test_a_named_give_plans_who_changes_and_gives_it_for_the_member(
    teabot_harness: HarnessFactory,
) -> None:
    harness, friends, _clan = await server(teabot_harness)
    sam = harness.guild.add_member(NONE, name="sam")
    ann = harness.guild.add_member(NONE, name="ann", roles=[friends])
    plan = await harness.plan(give, role=friends, members=[sam, ann])
    assert plan.counts == {"give": 1, "skip": 1}
    await harness.confirm(plan)
    assert friends.id in sam.role_ids
    assert sam.reasons == [f"via teabot: roles.give, for member {harness.member.id}"]


async def test_a_named_take_refuses_a_role_above_the_member(teabot_harness: HarnessFactory) -> None:
    harness, friends, _clan = await server(teabot_harness)
    mod = harness.guild.add_member(ADMIN, roles=[harness.guild.add_role("Helper", position=1)])
    sam = harness.guild.add_member(NONE, roles=[friends])
    try:
        await harness.as_member(mod).plan(take, role=friends, members=[sam])
    except Exception as refused:
        assert "at or above your highest role" in str(refused)
    else:
        raise AssertionError("expected a refusal")


async def test_a_matching_take_runs_as_a_job_and_records_its_outcome(teabot_harness: HarnessFactory) -> None:
    harness, friends, clan = await server(teabot_harness)
    both = [
        harness.guild.add_member(NONE, name=f"m{i}", roles=[friends, clan], cached=False) for i in range(3)
    ]
    friend_only = harness.guild.add_member(NONE, name="f", roles=[friends], cached=False)
    await directory(harness, [*both, friend_only])
    raw = {"role": str(friends.id), "roles_any": [str(clan.id)]}
    plan = await call(harness, "roles.take_matching", raw)
    assert isinstance(plan, Planned)
    assert plan.notes[0].startswith("Take Friends from people who have")
    assert plan.notes[1].startswith("3 members change.")
    await call(harness, "roles.take_matching", raw | {"confirm": plan.confirm})
    await finish(harness)
    assert all(friends.id not in m.role_ids for m in both)
    assert friends.id in friend_only.role_ids
    [listed] = (await call(harness, "roles.list_changes", {})).items
    assert (listed.state, listed.changed, listed.pending) == ("done", 3, 0)
    db: Any = harness.admin
    outcome = await db.fetchval("SELECT input FROM core.audit_log WHERE follows IS NOT NULL")
    assert json.loads(outcome)["outcome"].startswith("Change 1: 3 changed")


async def test_a_stopped_change_goes_no_further_and_a_revert_undoes_one(
    teabot_harness: HarnessFactory,
) -> None:
    harness, friends, clan = await server(teabot_harness)
    members = [
        harness.guild.add_member(NONE, name=f"m{i}", roles=[friends, clan], cached=False) for i in range(2)
    ]
    await directory(harness, members)
    await confirmed(harness, "roles.take_matching", {"role": str(friends.id), "roles_any": [str(clan.id)]})
    assert all(friends.id not in m.role_ids for m in members)
    plan = await call(harness, "roles.revert", {"change": 1})
    assert isinstance(plan, Planned)
    await call(harness, "roles.revert", {"change": 1, "confirm": plan.confirm})
    db: Any = harness.admin
    await db.execute("UPDATE core.members SET role_ids = array_remove(role_ids, $1)", friends.id)
    await finish(harness)
    assert all(friends.id in m.role_ids for m in members)


async def test_through_a_token_door_a_dangerous_role_is_refused(teabot_harness: HarnessFactory) -> None:
    harness, _friends, clan = await server(teabot_harness)
    harness.member.guild_permissions = discord.Permissions.all()
    mods = harness.guild.add_role("Helpers", position=4, permissions=discord.Permissions(kick_members=True))
    await directory(harness, [])
    try:
        await call(harness, "roles.give_matching", {"role": str(mods.id), "roles_any": [str(clan.id)]})
    except Exception as refused:
        assert "AI assistant cannot give or take it" in str(refused)
    else:
        raise AssertionError("expected a refusal")
