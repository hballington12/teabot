"""The harness's typed helpers: call, plan, confirm, as_member, configure, and the test clock."""

from datetime import datetime, timedelta
from pathlib import Path

import discord
import pytest
from pydantic import BaseModel

from teabot.sdk import DESTRUCTIVE, READ, Context, Diff, DiffEntry, Plugin, TextChannel
from teabot.testing import FakeChannel, HarnessFactory, Planned, PluginHarness, Refused

MIGRATIONS = Path(__file__).parent / "helpers_migrations"


class Cfg(BaseModel):
    greeting: str = "hi"


class Times(BaseModel):
    python: datetime
    sql: datetime


plugin = Plugin("clocky", config=Cfg, migrations=MIGRATIONS)
type Ctx = Context[Cfg]


@plugin.action(needs="manage_messages")
async def greet(ctx: Ctx, channel: TextChannel, name: str) -> str:
    """Greet someone in a channel.

    Args:
        channel: Where to greet them.
        name: Who to greet.
    """
    await channel.send(f"{ctx.config.greeting} {name}")
    return f"greeted {name}"


@plugin.action(risk=READ)
async def times(ctx: Ctx) -> Times:
    """The time, as Python and SQL see it."""
    return Times(python=ctx.now, sql=await ctx.db.fetchval(datetime, "SELECT now()"))


@plugin.action()
async def later(ctx: Ctx, minutes: int) -> str:
    """Note something later.

    Args:
        minutes: How long from now.
    """
    async with ctx.db.transaction() as tx:
        await tx.schedule(note.bind(text="later"), at=ctx.now + timedelta(minutes=minutes))
    return "scheduled"


@plugin.action(risk=DESTRUCTIVE)
async def clear(ctx: Ctx) -> str:
    """Clear the notes."""
    await ctx.db.execute("DELETE FROM notes WHERE guild_id = $1", ctx.guild.id)
    return "cleared"


@clear.plan
async def plan_clear(ctx: Ctx) -> Diff:
    rows = await ctx.db.fetch(str, "SELECT text FROM notes WHERE guild_id = $1", ctx.guild.id)
    return Diff(entries=[DiffEntry(change="remove", target=text) for text in rows])


@plugin.job
async def note(ctx: Ctx, text: str) -> None:
    await ctx.db.execute("INSERT INTO notes (guild_id, text) VALUES ($1, $2)", ctx.guild.id, text)


async def notes(harness: PluginHarness) -> list[str]:
    return list(
        await harness.admin.fetchval("SELECT coalesce(array_agg(text), '{}') FROM plugin_clocky.notes")
    )


async def test_call_is_typed_and_returns_what_the_function_returned(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    out: str = await harness.call(greet, channel=channel, name="Ann")
    assert out == "greeted Ann" and channel.sent[0].content == "hi Ann"


async def test_configure_sets_the_servers_config(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    await harness.configure(Cfg(greeting="welcome"))
    await harness.call(greet, channel=channel, name="Bo")
    assert channel.sent[0].content == "welcome Bo"


async def test_as_member_calls_with_that_members_permissions(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel = harness.guild.add_channel(FakeChannel())
    stranger = harness.guild.add_member(discord.Permissions.none())
    with pytest.raises(Refused) as caught:
        await harness.as_member(stranger).call(greet, channel=channel, name="Cy")
    assert caught.value.code == "forbidden"


async def test_advance_moves_python_and_sql_time_together(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    before = await harness.call(times)
    await harness.advance(days=2)
    after = await harness.call(times)
    assert timedelta(days=2) <= after.python - before.python < timedelta(days=2, minutes=1)
    assert timedelta(days=2) <= after.sql - before.sql < timedelta(days=2, minutes=1)


async def test_a_scheduled_job_runs_once_time_passes_it(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    await harness.call(later, minutes=30)
    await harness.run_jobs()
    assert await notes(harness) == []
    await harness.advance(minutes=31)
    await harness.run_jobs()
    assert await notes(harness) == ["later"]


async def test_plan_and_confirm_run_a_destructive_action(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    await harness.call(later, minutes=0)
    await harness.run_jobs()
    plan = await harness.plan(clear)
    assert isinstance(plan, Planned) and plan.total == 1
    await harness.confirm(plan)
    assert await notes(harness) == []


async def test_a_plan_older_than_fifteen_minutes_is_refused(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    plan = await harness.plan(clear)
    await harness.advance(minutes=16)
    with pytest.raises(Refused) as caught:
        await harness.confirm(plan)
    assert caught.value.code == "plan_expired"


async def test_call_refuses_a_destructive_action(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    with pytest.raises(TypeError, match=r"use harness\.plan"):
        await harness.call(clear)
