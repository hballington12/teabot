"""Plan then apply (WP6.1, D21): a destructive action shows its diff, and applies only on a fresh, matching
plan confirmed by the same member within 15 minutes, as a job that reports progress."""

import json
from pathlib import Path
from typing import Any

import discord
import pytest
from pydantic import BaseModel

from teabot.core.plans import Planned, Queued, canonical, diff_hash
from teabot.core.registry import Refused
from teabot.sdk import ActionContext, ActionSpec, Diff, DiffEntry, Manifest, Registrar, Risk
from teabot.testing import PluginHarness

MIGRATIONS = Path(__file__).parent / "sweep_migrations"


class Wipe(BaseModel):
    prefix: str


class Wiped(BaseModel):
    removed: int


async def matching(ctx: ActionContext, prefix: str) -> list[str]:
    rows = await ctx.db.fetch(
        "SELECT name FROM items WHERE guild_id = $1 AND name LIKE $2 || '%' ORDER BY name",
        ctx.guild.id,
        prefix,
    )
    return [r["name"] for r in rows]


async def plan(ctx: ActionContext, data: Wipe) -> Diff:
    return Diff(
        entries=[DiffEntry(change="remove", target=name) for name in await matching(ctx, data.prefix)]
    )


async def wipe(ctx: ActionContext, data: Wipe) -> Wiped:
    names = await matching(ctx, data.prefix)
    for done, name in enumerate(names, start=1):
        await ctx.db.execute("DELETE FROM items WHERE guild_id = $1 AND name = $2", ctx.guild.id, name)
        await ctx.report({"done": done, "total": len(names)})
    if data.prefix == "boom":
        raise RuntimeError("half done")
    return Wiped(removed=len(names))


class Sweep:
    manifest = Manifest("sweep", "1.0", migrations=MIGRATIONS)

    def setup(self, registrar: Registrar) -> None:
        registrar.action(
            ActionSpec("sweep.wipe", "Remove items", Wipe, Wiped, Risk.DESTRUCTIVE, wipe, plan=plan)
        )


@pytest.fixture
async def harness(teabot_harness: Any) -> PluginHarness:
    harness = await teabot_harness(Sweep())
    for name in ("apple", "apricot", "banana", "boomerang"):
        await harness.admin.execute("INSERT INTO plugin_sweep.items VALUES ($1, $2)", harness.guild.id, name)
    return harness


async def planned(harness: PluginHarness, prefix: str = "ap", user: int | None = None) -> Planned:
    out = await harness.invoke("sweep.wipe", {"prefix": prefix}, user=user)
    assert isinstance(out, Planned)
    return out


async def items(harness: PluginHarness) -> list[str]:
    return [r["name"] for r in await harness.admin.fetch("SELECT name FROM plugin_sweep.items ORDER BY name")]


async def test_without_confirm_the_action_only_plans(harness: PluginHarness) -> None:
    out = await planned(harness)
    assert (out.counts, [e.target for e in out.entries], out.total, out.stale) == (
        {"remove": 2},
        ["apple", "apricot"],
        2,
        False,
    )
    assert len(out.confirm) == 22
    assert await items(harness) == ["apple", "apricot", "banana", "boomerang"]
    row = await harness.admin.fetchrow(
        "SELECT outcome, diff_hash, confirm FROM core.audit_log WHERE action = 'sweep.wipe'"
    )
    assert (
        row is not None and (row["outcome"], row["confirm"]) == ("planned", out.confirm) and row["diff_hash"]
    )
    assert await harness.admin.fetchval("SELECT count(*) FROM core.jobs WHERE handler = 'post_audit'") == 0


async def test_a_confirmed_plan_applies_as_a_job_that_reports_progress(harness: PluginHarness) -> None:
    plan_out = await planned(harness)
    queued = await harness.invoke("sweep.wipe", {"prefix": "ap", "confirm": plan_out.confirm})
    assert isinstance(queued, Queued)
    assert await items(harness) == ["apple", "apricot", "banana", "boomerang"]
    await harness.run_jobs()
    assert await items(harness) == ["banana", "boomerang"]
    status = (await harness.invoke("admin.job_status", {"job_id": queued.job_id})).model_dump()
    assert (status["state"], status["progress"]) == ("done", {"done": 2, "total": 2})
    apply_row = await harness.admin.fetchrow(
        "SELECT outcome, plan_id, job_id FROM core.audit_log WHERE id = $1", queued.audit_id
    )
    plan_id = await harness.admin.fetchval(
        "SELECT id FROM core.audit_log WHERE confirm = $1", plan_out.confirm
    )
    assert apply_row is not None and (apply_row["outcome"], apply_row["plan_id"], apply_row["job_id"]) == (
        "ok",
        plan_id,
        queued.job_id,
    )


async def test_a_plan_whose_target_changed_is_refused_with_a_fresh_plan(harness: PluginHarness) -> None:
    old = await planned(harness)
    await harness.admin.execute("INSERT INTO plugin_sweep.items VALUES ($1, 'apex')", harness.guild.id)
    fresh = await harness.invoke("sweep.wipe", {"prefix": "ap", "confirm": old.confirm})
    assert isinstance(fresh, Planned) and fresh.stale and fresh.confirm != old.confirm
    assert fresh.counts == {"remove": 3}
    assert await harness.admin.fetchval("SELECT count(*) FROM core.jobs WHERE handler = 'apply'") == 0
    refused = await harness.admin.fetchval("SELECT error FROM core.audit_log WHERE outcome = 'refused'")
    assert refused == "plan_stale"


@pytest.mark.parametrize(
    ("change", "code"),
    [
        ("member", "confirm_mismatch"),
        ("input", "confirm_mismatch"),
        ("unknown", "confirm_unknown"),
        ("expired", "plan_expired"),
        ("used", "plan_used"),
    ],
)
async def test_a_confirm_value_is_refused_unless_it_is_this_members_live_unused_plan(
    harness: PluginHarness, change: str, code: str
) -> None:
    out = await planned(harness)
    confirm, raw, user = out.confirm, {"prefix": "ap"}, None
    if change == "member":
        user = harness.guild.add_member(discord.Permissions.all()).id
    elif change == "input":
        raw = {"prefix": "a"}
    elif change == "unknown":
        confirm = "x" * 22
    elif change == "expired":
        await harness.admin.execute(
            "UPDATE core.audit_log SET time = now() - interval '16 minutes' WHERE confirm = $1", confirm
        )
    elif change == "used":
        await harness.invoke("sweep.wipe", {"prefix": "ap", "confirm": confirm})
    with pytest.raises(Refused) as caught:
        await harness.invoke("sweep.wipe", {**raw, "confirm": confirm}, user=user)
    assert caught.value.code == code


async def test_a_failed_apply_is_recorded_and_never_retried(harness: PluginHarness) -> None:
    out = await planned(harness, "boom")
    queued = await harness.invoke("sweep.wipe", {"prefix": "boom", "confirm": out.confirm})
    assert isinstance(queued, Queued)
    await harness.run_jobs()
    job = await harness.admin.fetchrow(
        "SELECT state, attempts, max_attempts, last_error FROM core.jobs WHERE id = $1", queued.job_id
    )
    assert (
        job is not None
        and (job["state"], job["attempts"], job["max_attempts"]) == ("failed", 1, 1)
        and "half done" in job["last_error"]
    )
    row = await harness.admin.fetchrow(
        "SELECT outcome, error FROM core.audit_log WHERE id = $1", queued.audit_id
    )
    assert row is not None and row["outcome"] == "error" and "half done" in row["error"]


async def test_the_apply_checks_the_members_permission_again(harness: PluginHarness) -> None:
    member = harness.guild.add_member(discord.Permissions.all())
    out = await planned(harness, user=member.id)
    queued = await harness.invoke("sweep.wipe", {"prefix": "ap", "confirm": out.confirm}, user=member.id)
    assert isinstance(queued, Queued)
    del harness.guild.members[member.id]
    await harness.run_jobs()
    assert await items(harness) == ["apple", "apricot", "banana", "boomerang"]
    assert (
        await harness.admin.fetchval("SELECT outcome FROM core.audit_log WHERE id = $1", queued.audit_id)
        == "refused"
    )


def test_the_hash_is_of_the_diff_not_its_order() -> None:
    a = Diff(entries=[DiffEntry(change="remove", target="x"), DiffEntry(change="skip", target="y")])
    b = Diff(entries=[DiffEntry(change="skip", target="y"), DiffEntry(change="remove", target="x")])
    assert diff_hash(a) == diff_hash(b)
    assert diff_hash(a) != diff_hash(Diff(entries=[DiffEntry(change="remove", target="x")]))
    assert json.loads(json.dumps(a.counts)) == {"remove": 1, "skip": 1}


def test_entries_that_differ_only_in_detail_still_have_one_order() -> None:
    plain = DiffEntry(change="remove", target="x")
    noted = DiffEntry(change="remove", target="x", detail="kept a copy")
    assert canonical(Diff(entries=[noted, plain])) == canonical(Diff(entries=[plain, noted]))
    assert canonical(Diff(entries=[noted, plain])).index("kept a copy") > canonical(
        Diff(entries=[plain])
    ).index("x")
