"""Work that outlasts its apply (role-changes.md): an apply returns `HandedOff`, its audit row ends "handed off",
and the job it queued checks its grant, which a later loss of permission ends, and records its outcome once."""

import json
from typing import Any

import discord

from teabot.sdk import DESTRUCTIVE, Context, Diff, DiffEntry, EmptyConfig, HandedOff, NotAuthorized, Plugin
from teabot.testing import HarnessFactory, PluginHarness

plugin = Plugin("handoff")
type Ctx = Context[EmptyConfig]
heard: list[str] = []


@plugin.job
async def carry_on(ctx: Ctx, grant: int) -> None:
    try:
        actor = await ctx.authorized(grant)
    except NotAuthorized as stop:
        heard.append(f"stopped: {stop}")
        await ctx.record_outcome(grant, f"stopped: {stop}", failed=True)
        return
    heard.append(f"for {actor.user_id}")
    await ctx.record_outcome(grant, "done: 3 changed")
    await ctx.record_outcome(grant, "a second outcome is ignored")


@plugin.action(risk=DESTRUCTIVE, needs="manage_roles")
async def big(ctx: Ctx) -> HandedOff:
    """Change a lot."""
    assert ctx.audit_id is not None
    async with ctx.db.transaction() as tx:
        await tx.schedule(carry_on.bind(grant=ctx.audit_id))
    return HandedOff(id="1", text="Change 1 is under way.")


@big.plan
async def plan_big(ctx: Ctx) -> Diff:
    return Diff(entries=[DiffEntry(change="give", target="everyone")], notes=["Give Friends to 3 members."])


async def setup(teabot_harness: HarnessFactory) -> PluginHarness:
    heard.clear()
    harness = await teabot_harness(plugin)
    harness.member.guild_permissions = discord.Permissions(manage_roles=True)
    return harness


async def outcomes(harness: PluginHarness) -> list[Any]:
    db: Any = harness.admin
    return await db.fetch(
        "SELECT outcome, input, follows IS NOT NULL AS follows FROM core.audit_log WHERE action = 'handoff.big' "
        "AND outcome IN ('handed_off', 'ok', 'error') ORDER BY id"
    )


async def test_a_handed_off_apply_is_followed_by_its_jobs_outcome(teabot_harness: HarnessFactory) -> None:
    harness = await setup(teabot_harness)
    plan = await harness.plan(big)
    assert plan.notes == ["Give Friends to 3 members."]
    await harness.confirm(plan)
    assert heard == [f"for {harness.member.id}"]
    rows = await outcomes(harness)
    assert [(r["outcome"], r["follows"]) for r in rows] == [("handed_off", False), ("ok", True)]
    assert json.loads(rows[1]["input"]) == {"outcome": "done: 3 changed"}


async def test_a_member_who_loses_the_permission_stops_the_work(teabot_harness: HarnessFactory) -> None:
    harness = await setup(teabot_harness)
    await harness.confirm(await harness.plan(big))
    db: Any = harness.admin
    grant = await db.fetchval("SELECT id FROM core.audit_log WHERE outcome = 'handed_off'")
    await db.execute("DELETE FROM core.audit_log WHERE follows = $1", grant)
    harness.member.guild_permissions = discord.Permissions.none()
    heard.clear()
    await harness.run_job(carry_on.bind(grant=grant))
    assert heard == ["stopped: handoff.big needs permissions you do not have"]
    rows = await outcomes(harness)
    assert rows[-1]["outcome"] == "error"


async def test_a_grant_from_another_action_is_not_this_jobs(teabot_harness: HarnessFactory) -> None:
    harness = await setup(teabot_harness)
    await harness.confirm(await harness.plan(big))
    db: Any = harness.admin
    plan_row = await db.fetchval("SELECT id FROM core.audit_log WHERE outcome = 'planned'")
    heard.clear()
    await harness.run_job(carry_on.bind(grant=plan_row))
    assert heard == ["stopped: that grant is not a change handed off from its apply"]
