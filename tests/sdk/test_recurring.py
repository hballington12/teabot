"""A recurring job runs on its own, once per interval, in each server where its plugin is on."""

from datetime import timedelta

import pytest

from teabot.sdk import Context, EmptyConfig, Plugin
from teabot.sdk._signature import SignatureError
from teabot.testing import HarnessFactory, PluginHarness

plugin = Plugin("digest")
type Ctx = Context[EmptyConfig]
runs: list[int] = []


@plugin.job(every=timedelta(days=1))
async def daily(ctx: Ctx) -> None:
    runs.append(ctx.guild.id)
    if len(runs) == 2:
        raise RuntimeError("a bad day")


@pytest.fixture
async def harness(teabot_harness: HarnessFactory) -> PluginHarness:
    runs.clear()
    return await teabot_harness(plugin)


async def pending(harness: PluginHarness) -> int:
    return await harness.admin.fetchval(
        "SELECT count(*) FROM core.jobs WHERE plugin_id = 'digest' AND handler = 'daily' AND state = 'pending'"
    )


async def test_it_runs_once_a_day_and_a_failed_run_does_not_end_it(harness: PluginHarness) -> None:
    await harness.run_jobs()
    assert runs == []
    for _ in range(3):
        await harness.advance(days=1)
        await harness.run_jobs(raise_failures=False)
    # Three days' runs, and the retry of the second, which failed.
    assert runs == [harness.guild.id] * 4
    assert await pending(harness) == 1


async def test_turning_the_plugin_on_again_keeps_one_pending_run(harness: PluginHarness) -> None:
    await harness.enable()
    await harness.enable()
    assert await pending(harness) == 1


def test_a_recurring_job_takes_no_payload_and_runs_at_most_each_minute() -> None:
    other = Plugin("digest2")

    async def with_payload(ctx: Context[EmptyConfig], day: int) -> None: ...

    async def too_often(ctx: Context[EmptyConfig]) -> None: ...

    with pytest.raises(SignatureError, match="takes no parameters"):
        other.job(every=timedelta(hours=1))(with_payload)
    with pytest.raises(SignatureError, match="the least is a minute"):
        other.job(every=timedelta(seconds=5))(too_often)
