"""An action or a job that takes longer than its limit is stopped, and the member or the job's record says so."""

import asyncio
from datetime import timedelta

import pytest

from teabot.core.registry import ActionFailed
from teabot.sdk import Context, EmptyConfig, Plugin
from teabot.testing import HarnessFactory, PluginHarness

plugin = Plugin("slow")
type Ctx = Context[EmptyConfig]


@plugin.action(timeout=timedelta(milliseconds=100))
async def hang(ctx: Ctx) -> str:
    """Never finish."""
    await asyncio.sleep(60)
    return "done"


@plugin.action()
async def start(ctx: Ctx) -> str:
    """Queue the hanging job."""
    async with ctx.db.transaction() as tx:
        await tx.schedule(stall.bind())
    return "queued"


@plugin.job(timeout=timedelta(milliseconds=100))
async def stall(ctx: Ctx) -> None:
    await asyncio.sleep(60)


@pytest.fixture
async def harness(teabot_harness: HarnessFactory) -> PluginHarness:
    return await teabot_harness(plugin)


async def test_an_action_past_its_limit_tells_the_member(harness: PluginHarness) -> None:
    with pytest.raises(ActionFailed) as caught:
        await harness.call(hang)
    assert caught.value.public_message == "That took too long, so it was stopped."
    error = await harness.admin.fetchval("SELECT error FROM core.audit_log WHERE action = 'slow.hang'")
    assert "took longer than 0.1 seconds" in error


async def test_a_job_past_its_limit_fails_and_retries(harness: PluginHarness) -> None:
    await harness.call(start)
    await harness.run_jobs(raise_failures=False)
    row = await harness.admin.fetchrow("SELECT state, last_error FROM core.jobs WHERE handler = 'stall'")
    assert row is not None and row["state"] == "pending"
    assert "took longer than 0.1 seconds" in row["last_error"]
