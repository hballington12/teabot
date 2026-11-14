"""teapot-devtools (WP2.9): its own table, the core refusing it, and a setup that can be made to fail."""

from typing import Any

import discord
import pytest

from teapot.testing import Planned, PluginHarness, Queued, Refused
from teapot_devtools import FAIL_SETUP, Noted, Peeked, plugin


async def test_notes_go_to_the_plugins_own_table(teapot_harness: Any) -> None:
    harness: PluginHarness = await teapot_harness(plugin)
    assert await harness.invoke("devtools.note", {"text": "one"}) == Noted(notes=1)
    assert await harness.invoke("devtools.note", {"text": "two"}) == Noted(notes=2)
    assert await harness.admin.fetchval("SELECT count(*) FROM plugin_devtools.notes") == 2


async def test_the_core_schema_refuses_the_plugin(teapot_harness: Any) -> None:
    harness: PluginHarness = await teapot_harness(plugin)
    out = await harness.invoke("devtools.peek_core", {})
    assert isinstance(out, Peeked) and "permission denied for schema core" in out.refusal


async def test_the_failure_switch_fails_setup(teapot_harness: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FAIL_SETUP, "1")
    with pytest.raises(RuntimeError, match=FAIL_SETUP):
        await teapot_harness(plugin)


async def notes(harness: PluginHarness, *texts: str) -> None:
    for text in texts:
        await harness.invoke("devtools.note", {"text": text})


async def test_clearing_notes_plans_first_then_applies_with_progress(teapot_harness: Any) -> None:
    harness: PluginHarness = await teapot_harness(plugin)
    await notes(harness, "buy milk", "bingo teams", "bingo prizes")
    plan = await harness.invoke("devtools.clear_notes", {"containing": "bingo"})
    assert isinstance(plan, Planned)
    assert (plan.counts, sorted(e.target for e in plan.entries)) == (
        {"remove": 2},
        ["bingo prizes", "bingo teams"],
    )
    queued = await harness.invoke("devtools.clear_notes", {"containing": "bingo", "confirm": plan.confirm})
    assert isinstance(queued, Queued)
    await harness.run_jobs()
    assert await harness.admin.fetchval("SELECT array_agg(text) FROM plugin_devtools.notes") == ["buy milk"]
    status = (await harness.invoke("admin.job_status", {"job_id": queued.job_id})).model_dump()
    assert (status["state"], status["progress"]) == ("done", {"done": 2, "total": 2})


async def test_an_empty_filter_clears_every_note(teapot_harness: Any) -> None:
    harness: PluginHarness = await teapot_harness(plugin)
    await notes(harness, "one", "two")
    plan = await harness.invoke("devtools.clear_notes", {})
    assert isinstance(plan, Planned) and plan.total == 2


async def test_a_note_added_after_the_plan_makes_it_stale(teapot_harness: Any) -> None:
    harness: PluginHarness = await teapot_harness(plugin)
    await notes(harness, "one")
    plan = await harness.invoke("devtools.clear_notes", {})
    assert isinstance(plan, Planned)
    await notes(harness, "two")
    fresh = await harness.invoke("devtools.clear_notes", {"confirm": plan.confirm})
    assert isinstance(fresh, Planned) and fresh.stale and fresh.total == 2


async def test_clearing_notes_needs_manage_server(teapot_harness: Any) -> None:
    harness: PluginHarness = await teapot_harness(plugin)
    member = harness.guild.add_member(discord.Permissions(manage_messages=True))
    with pytest.raises(Refused) as caught:
        await harness.invoke("devtools.clear_notes", {}, user=member.id)
    assert caught.value.code == "forbidden"
