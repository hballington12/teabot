"""Guild removal (WP3.4, D49): a grace period, a return within it, and the purge of every row after it."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from teabot.core.audit import ensure_read_partitions
from teabot.core.command_sync import CommandSync
from teabot.core.lifecycle import PURGE_GUILD, Guilds
from teabot.core.queue import JobContext, Queue, ShardFilter
from teabot.db.migrate import PluginMigrations, migrate
from teabot.db.naming import Naming
from teabot.db.pool import Pools
from teabot.db.types import Conn
from teabot.testing import FakeClient

HERE = 1001
THERE = 1002
# On shard 1 of 2: (guild_id >> 22) % 2 == 1.
ELSEWHERE = 1 << 22

CORE_TABLES_WITH_GUILD = (
    "guilds",
    "guild_plugins",
    "jobs",
    "audit_log",
    "audit_reads",
    "interaction_drafts",
    "command_sync",
)


@pytest.fixture
async def queue(admin: Conn, naming: Naming, pools: Pools, tmp_path: Path) -> Queue:
    directory = tmp_path / "alpha"
    directory.mkdir()
    (directory / "0001_t.sql").write_text("CREATE TABLE entries (guild_id bigint, note text);")
    await migrate(admin, naming, [PluginMigrations("alpha", directory)])
    await ensure_read_partitions(pools.core_db(), datetime.now(UTC).date(), days_ahead=1)
    for guild_id in (HERE, THERE):
        await admin.execute("INSERT INTO core.guilds (guild_id) VALUES ($1)", guild_id)
        await admin.execute("INSERT INTO plugin_alpha.entries VALUES ($1, 'x')", guild_id)
        await admin.execute(
            "INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled, config)"
            " VALUES ($1, 'alpha', true, '{\"a\": 1}')",
            guild_id,
        )
        await admin.execute(
            "INSERT INTO core.jobs (guild_id, plugin_id, handler) VALUES ($1, 'alpha', 'draw')", guild_id
        )
        await admin.execute(
            "INSERT INTO core.audit_log (guild_id, user_id, surface, action, input, risk, outcome)"
            " VALUES ($1, 5, 'slash', 'alpha.go', '{}', 1, 'ok')",
            guild_id,
        )
        await admin.execute(
            "INSERT INTO core.audit_reads (guild_id, user_id, surface, action, input, outcome)"
            " VALUES ($1, 5, 'slash', 'alpha.look', '{}', 'ok')",
            guild_id,
        )
        await admin.execute(
            "INSERT INTO core.interaction_drafts (id, guild_id, user_id, action, input)"
            " VALUES (gen_random_uuid(), $1, 5, 'alpha.go', '{}')",
            guild_id,
        )
        await admin.execute("INSERT INTO core.command_sync (guild_id, hash) VALUES ($1, 'h')", guild_id)
    return Queue(pools.core_db())


def guilds_for(queue: Queue, pools: Pools, days: int = 30) -> Guilds:
    return Guilds(pools, queue, CommandSync(pools.core_db(), queue, {}, FakeClient()), timedelta(days=days))


@pytest.fixture
def guilds(queue: Queue, pools: Pools) -> Guilds:
    return guilds_for(queue, pools)


async def rows_for(admin: Conn, guild_id: int) -> dict[str, int]:
    counts = {
        t: await admin.fetchval(f"SELECT count(*) FROM core.{t} WHERE guild_id = $1", guild_id)
        for t in CORE_TABLES_WITH_GUILD
    }
    counts["plugin_alpha.entries"] = await admin.fetchval(
        "SELECT count(*) FROM plugin_alpha.entries WHERE guild_id = $1", guild_id
    )
    return counts


async def purge_job(admin: Conn, guild_id: int) -> tuple[int, datetime] | None:
    row = await admin.fetchrow(
        "SELECT g.purge_job_id, j.run_at FROM core.guilds g JOIN core.jobs j ON j.id = g.purge_job_id"
        " WHERE g.guild_id = $1",
        guild_id,
    )
    return None if row is None else (row["purge_job_id"], row["run_at"])


async def run_due_purges(queue: Queue, guilds: Guilds, pools: Pools) -> int:
    ran = 0
    while (job := await queue.claim(["core"], None)) is not None:
        if job.handler == PURGE_GUILD:
            await guilds.purge(JobContext(job, pools.core_db()))
            ran += 1
        await queue.finish(job)
    return ran


async def test_a_removal_pauses_the_servers_jobs_and_queues_its_purge_after_the_grace_period(
    admin: Conn, queue: Queue, guilds: Guilds
) -> None:
    await guilds.removed(HERE)
    job = await purge_job(admin, HERE)
    assert job is not None
    assert timedelta(days=29, hours=23) < job[1] - datetime.now(UTC) <= timedelta(days=30)
    claimed = await queue.claim(["alpha"], None)
    assert claimed is not None and claimed.guild_id == THERE
    assert await queue.claim(["alpha"], None) is None


async def test_a_second_removal_event_queues_no_second_purge(admin: Conn, guilds: Guilds) -> None:
    await guilds.removed(HERE)
    first = await purge_job(admin, HERE)
    await guilds.removed(HERE)
    assert await purge_job(admin, HERE) == first
    assert await admin.fetchval("SELECT count(*) FROM core.jobs WHERE handler = $1", PURGE_GUILD) == 1


async def test_a_return_within_the_grace_period_keeps_everything_and_cancels_the_purge(
    admin: Conn, queue: Queue, guilds: Guilds
) -> None:
    await guilds.removed(HERE)
    job = await purge_job(admin, HERE)
    assert job is not None
    await guilds.joined(HERE)
    assert await admin.fetchval("SELECT state FROM core.jobs WHERE id = $1", job[0]) == "cancelled"
    assert await admin.fetchval("SELECT removed_at FROM core.guilds WHERE guild_id = $1", HERE) is None
    assert (
        await admin.fetchval("SELECT config->>'a' FROM core.guild_plugins WHERE guild_id = $1", HERE) == "1"
    )
    assert {(await queue.claim(["alpha"], None)).guild_id for _ in range(2)} == {HERE, THERE}  # type: ignore[union-attr]


async def test_after_the_grace_period_every_row_for_the_server_is_deleted(
    admin: Conn, queue: Queue, pools: Pools
) -> None:
    guilds = guilds_for(queue, pools, days=0)
    await guilds.removed(HERE)
    assert await run_due_purges(queue, guilds, pools) == 1
    assert set((await rows_for(admin, HERE)).values()) == {0}
    assert set((await rows_for(admin, THERE)).values()) == {1}


async def test_a_purge_for_a_server_that_came_back_deletes_nothing(
    admin: Conn, queue: Queue, pools: Pools
) -> None:
    guilds = guilds_for(queue, pools, days=0)
    await guilds.removed(HERE)
    job = await queue.claim(["core"], None)
    assert job is not None and job.handler == PURGE_GUILD
    await admin.execute("UPDATE core.guilds SET removed_at = NULL WHERE guild_id = $1", HERE)
    await guilds.purge(JobContext(job, pools.core_db()))
    assert (await rows_for(admin, HERE))["plugin_alpha.entries"] == 1


async def test_a_removal_forgets_the_synced_commands_and_a_join_queues_a_sync(
    admin: Conn, guilds: Guilds
) -> None:
    await guilds.removed(HERE)
    assert await admin.fetchval("SELECT count(*) FROM core.command_sync WHERE guild_id = $1", HERE) == 0
    await guilds.joined(HERE)
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM core.jobs WHERE handler = 'sync_commands' AND guild_id = $1", HERE
        )
        == 1
    )


async def test_a_new_server_is_recorded(admin: Conn, guilds: Guilds) -> None:
    await guilds.joined(4242)
    assert await admin.fetchval("SELECT removed_at IS NULL FROM core.guilds WHERE guild_id = 4242") is True


async def test_startup_finds_servers_joined_and_left_while_the_bot_was_down(
    admin: Conn, guilds: Guilds
) -> None:
    await admin.execute("INSERT INTO core.guilds (guild_id) VALUES ($1)", ELSEWHERE)
    assert await guilds.reconcile([HERE, 4242], ShardFilter(shard_count=2, shard_ids=(0,))) == (1, 1)
    assert (
        await admin.fetchval("SELECT removed_at IS NOT NULL FROM core.guilds WHERE guild_id = $1", THERE)
        is True
    )
    assert await admin.fetchval("SELECT count(*) FROM core.guilds WHERE guild_id = 4242") == 1
    assert await admin.fetchval("SELECT removed_at FROM core.guilds WHERE guild_id = $1", ELSEWHERE) is None
    assert await guilds.reconcile([HERE, 4242], ShardFilter(shard_count=2, shard_ids=(0,))) == (0, 0)


async def test_startup_without_a_shard_filter_compares_every_server(admin: Conn, guilds: Guilds) -> None:
    assert await guilds.reconcile([HERE], None) == (0, 1)
