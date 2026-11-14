"""teabot-devtools: its own table, the core refusing it, and a setup that can be made to fail."""

import discord
import pytest

from teabot.testing import HarnessFactory, Planned, PluginHarness, Refused
from teabot_devtools import FAIL_SETUP, Noted, clear_notes, note, peek_core, plugin


async def notes(harness: PluginHarness, *texts: str) -> None:
    for text in texts:
        await harness.call(note, text=text)


async def remaining(harness: PluginHarness) -> list[str]:
    return list(
        await harness.admin.fetchval("SELECT coalesce(array_agg(text), '{}') FROM plugin_devtools.notes")
    )


async def test_notes_go_to_the_plugins_own_table(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    assert await harness.call(note, text="one") == Noted(notes=1)
    assert await harness.call(note, text="two") == Noted(notes=2)
    assert await remaining(harness) == ["one", "two"]


async def test_the_core_schema_refuses_the_plugin(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    out = await harness.call(peek_core)
    assert "permission denied for schema core" in out.refusal


async def test_the_failure_switch_fails_setup(
    teabot_harness: HarnessFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(FAIL_SETUP, "1")
    with pytest.raises(RuntimeError, match=FAIL_SETUP):
        await teabot_harness(plugin)


async def test_clearing_notes_plans_first_then_applies_with_progress(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    await notes(harness, "buy milk", "bingo teams", "bingo prizes")
    plan = await harness.plan(clear_notes, containing="bingo")
    assert (plan.counts, sorted(e.target for e in plan.entries)) == (
        {"remove": 2},
        ["bingo prizes", "bingo teams"],
    )
    await harness.confirm(plan)
    assert await remaining(harness) == ["buy milk"]
    job_id = await harness.admin.fetchval("SELECT max(id) FROM core.jobs WHERE handler = 'apply'")
    status = (await harness.invoke("admin.job_status", {"job_id": job_id})).model_dump()
    assert (status["state"], status["progress"], status["label"]) == (
        "done",
        {"done": 2, "total": 2},
        "devtools.clear_notes",
    )


async def test_an_empty_filter_clears_every_note(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    await notes(harness, "one", "two")
    assert (await harness.plan(clear_notes)).total == 2


async def test_a_note_added_after_the_plan_makes_it_stale(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    await notes(harness, "one")
    plan = await harness.plan(clear_notes)
    await notes(harness, "two")
    fresh = await harness.invoke("devtools.clear_notes", {"confirm": plan.confirm})
    assert isinstance(fresh, Planned) and fresh.stale and fresh.total == 2


async def test_clearing_notes_needs_manage_server(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    member = harness.guild.add_member(discord.Permissions(manage_messages=True))
    with pytest.raises(Refused) as caught:
        await harness.as_member(member).plan(clear_notes)
    assert caught.value.code == "forbidden"
