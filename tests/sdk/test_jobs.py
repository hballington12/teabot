"""Typed jobs: bound arguments, keys that move or cancel a pending job, and who started a job."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from teabot.sdk import SYSTEM, Context, Plugin
from teabot.testing import PluginHarness

MIGRATIONS = Path(__file__).parent / "jobs_migrations"


class Cfg(BaseModel):
    prefix: str = "seen"


plugin = Plugin("ticker", config=Cfg, migrations=MIGRATIONS)
type Ctx = Context[Cfg]
LATER = datetime(2099, 1, 1, tzinfo=UTC)


@plugin.action()
async def remind(ctx: Ctx, note: str, minutes: int = 0) -> str:
    """Remind about something later.

    Args:
        note: What to be reminded of.
        minutes: How long from now.
    """
    async with ctx.db.transaction() as tx:
        await tx.schedule(tick.bind(note=note), at=ctx.now + timedelta(minutes=minutes))
    return "ok"


@plugin.action()
async def forget(ctx: Ctx, note: str) -> str:
    """Forget a reminder.

    Args:
        note: The reminder to forget.
    """
    async with ctx.db.transaction() as tx:
        gone = await tx.unschedule(tick.bind(note=note))
    return "gone" if gone else "none"


@plugin.job
async def tick(ctx: Ctx, note: str) -> None:
    await ctx.db.execute(
        "INSERT INTO ticks (guild_id, note, actor) VALUES ($1, $2, $3)",
        ctx.guild.id,
        f"{ctx.config.prefix} {note}",
        ctx.actor.user_id,
    )
    if note == "chain":
        async with ctx.db.transaction() as tx:
            await tx.schedule(tick.bind(note="chained"))


async def pending(harness: PluginHarness) -> list[tuple[str, Any]]:
    rows = await harness.admin.fetch(
        "SELECT key, run_at FROM core.jobs WHERE plugin_id = 'ticker' AND state = 'pending' ORDER BY id"
    )
    return [(r["key"], r["run_at"]) for r in rows]


async def test_scheduling_the_same_bound_job_again_moves_it(teabot_harness: Any) -> None:
    harness: PluginHarness = await teabot_harness(plugin)
    await harness.invoke("ticker.remind", {"note": "tea", "minutes": 10})
    await harness.invoke("ticker.remind", {"note": "tea", "minutes": 30})
    await harness.invoke("ticker.remind", {"note": "cake", "minutes": 10})
    jobs = await pending(harness)
    assert [key for key, _ in jobs] == ['tick:{"note": "tea"}', 'tick:{"note": "cake"}']
    assert jobs[0][1] - jobs[1][1] > timedelta(minutes=19)


async def test_unschedule_cancels_the_pending_job(teabot_harness: Any) -> None:
    harness: PluginHarness = await teabot_harness(plugin)
    await harness.invoke("ticker.remind", {"note": "tea", "minutes": 10})
    assert (await harness.invoke("ticker.forget", {"note": "tea"})).model_dump() == {"text": "gone"}
    assert (await harness.invoke("ticker.forget", {"note": "tea"})).model_dump() == {"text": "none"}
    assert await pending(harness) == []


async def test_a_job_knows_who_started_it_and_its_servers_config(teabot_harness: Any) -> None:
    harness: PluginHarness = await teabot_harness(plugin)
    await harness.invoke("plugins.config", {"plugin": "ticker", "setting": "prefix", "value": "noted"})
    await harness.invoke("ticker.remind", {"note": "chain"})
    await harness.run_jobs()
    await harness.run_jobs()
    rows = await harness.admin.fetch("SELECT note, actor FROM plugin_ticker.ticks ORDER BY note")
    assert [(r["note"], r["actor"]) for r in rows] == [
        ("noted chain", harness.member.id),
        ("noted chained", harness.member.id),
    ]


async def test_a_job_nobody_started_runs_as_the_system(teabot_harness: Any) -> None:
    harness: PluginHarness = await teabot_harness(plugin)
    await harness.admin.execute(
        "INSERT INTO core.jobs (guild_id, plugin_id, handler, payload) VALUES ($1, 'ticker', 'tick', $2)",
        harness.guild.id,
        '{"note": "cron"}',
    )
    await harness.run_jobs()
    assert await harness.admin.fetchval("SELECT actor FROM plugin_ticker.ticks") == SYSTEM


def test_bind_checks_its_arguments_into_a_json_payload() -> None:
    bound = tick.bind(note="tea")
    assert (bound.handler, dict(bound.payload), bound.key) == (
        "tick",
        {"note": "tea"},
        'tick:{"note": "tea"}',
    )
