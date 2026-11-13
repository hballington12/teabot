"""The core's maintenance job (WP1.7): prune finished jobs and stale process rows, then come back tomorrow."""

import pytest

from teapot.core.maintenance import Maintenance
from teapot.core.queue import NewJob, Queue
from teapot.core.worker import Workers
from teapot.db.migrate import migrate
from teapot.db.naming import Naming
from teapot.db.pool import Pools
from teapot.db.types import Conn


@pytest.fixture
async def queue(admin: Conn, naming: Naming, pools: Pools) -> Queue:
    await migrate(admin, naming, [])
    queue = Queue(pools.core_db())
    queue.register("core", "maintenance", Maintenance(queue, retention_days=30, batch=2))
    return queue


async def add_job(admin: Conn, state: str, age_days: int) -> int:
    job_id: int = await admin.fetchval(
        "INSERT INTO core.jobs (plugin_id, handler, state, finished_at) "
        "VALUES ('core', 'x', $1, now() - make_interval(days => $2)) RETURNING id",
        state,
        age_days,
    )
    return job_id


async def run_maintenance(queue: Queue) -> None:
    await queue.schedule(NewJob("core", "maintenance"))
    assert await Workers(queue, lambda: ["core"]).run_once()


async def test_old_finished_jobs_are_pruned_and_the_rest_kept(queue: Queue, admin: Conn) -> None:
    old = [await add_job(admin, state, 31) for state in ("done", "failed", "cancelled", "done", "done")]
    recent = await add_job(admin, "done", 29)
    pending_old = await admin.fetchval(
        "INSERT INTO core.jobs (plugin_id, handler, run_at) VALUES ('core', 'x', now() + interval '1 day') RETURNING id"
    )
    await run_maintenance(queue)
    remaining = {r["id"] for r in await admin.fetch("SELECT id FROM core.jobs WHERE handler = 'x'")}
    assert remaining == {recent, pending_old}
    assert not remaining & set(old)


async def test_stale_process_rows_are_removed(queue: Queue, admin: Conn) -> None:
    for name, minutes in (("stale", 11), ("fresh", 1)):
        await admin.execute(
            "INSERT INTO core.processes (process_id, host, shard_ids, shard_count, version, updated_at) "
            "VALUES ($1, 'h', '{0}', 1, 'v', now() - make_interval(mins => $2))",
            name,
            minutes,
        )
    await run_maintenance(queue)
    assert [r["process_id"] for r in await admin.fetch("SELECT process_id FROM core.processes")] == ["fresh"]


async def test_it_reschedules_itself_once_a_day_and_never_twice(queue: Queue, admin: Conn) -> None:
    await run_maintenance(queue)
    await run_maintenance(queue)
    rows = await admin.fetch(
        "SELECT run_at - now() AS wait FROM core.jobs WHERE handler = 'maintenance' AND state = 'pending'"
    )
    assert len(rows) == 1
    assert 23 * 3600 < rows[0]["wait"].total_seconds() <= 24 * 3600
