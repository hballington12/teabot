"""The work queue and its workers, used the way the core and plugins use them (WP1.6)."""

import asyncio
import json
import time
from collections import Counter
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from teabot.core.processes import open_lock_connection
from teabot.core.queue import NOTIFY_CHANNEL, Job, JobContext, NewJob, Queue, ShardFilter
from teabot.core.worker import Workers, seed_maintenance
from teabot.db.migrate import PluginMigrations, migrate
from teabot.db.naming import Naming
from teabot.db.pool import Login, Pools
from teabot.db.types import Conn

SHARD0_GUILD = 0 << 22 | 7
SHARD1_GUILD = 1 << 22 | 7


@pytest.fixture
async def queue(admin: Conn, naming: Naming, pools: Pools, tmp_path: Path) -> Queue:
    plugin_dir = tmp_path / "alpha"
    plugin_dir.mkdir()
    (plugin_dir / "0001_t.sql").write_text("CREATE TABLE t (guild_id bigint);")
    await migrate(admin, naming, [PluginMigrations("alpha", plugin_dir)])
    for guild in (SHARD0_GUILD, SHARD1_GUILD):
        await admin.execute(
            "INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled) VALUES ($1, 'alpha', true)", guild
        )
    return Queue(pools.core_db())


async def job_state(admin: Conn, job_id: int) -> dict[str, object]:
    row = await admin.fetchrow(
        "SELECT state, attempts, last_error, run_at > now() AS later FROM core.jobs WHERE id = $1", job_id
    )
    assert row is not None
    return dict(row)


async def test_each_job_runs_exactly_once_across_two_worker_pools(queue: Queue) -> None:
    runs: Counter[int] = Counter()
    all_ran = asyncio.Event()

    async def record(ctx: JobContext) -> None:
        runs[ctx.job.payload["n"]] += 1
        await asyncio.sleep(0.01)
        if sum(runs.values()) == 40:
            all_ran.set()

    queue.register("alpha", "record", record)
    for n in range(40):
        await queue.schedule(NewJob("alpha", "record", guild_id=SHARD0_GUILD, payload={"n": n}))
    pools = [Workers(queue, lambda: ["alpha"], count=4, poll_seconds=0.05) for _ in range(2)]
    for w in pools:
        w.start()
    await asyncio.wait_for(all_ran.wait(), timeout=10)
    await asyncio.sleep(0.2)
    for w in pools:
        await w.stop()
    assert runs == Counter(range(40))


@pytest.mark.parametrize("pause", ["plugin not loaded", "plugin disabled", "bot left the server"])
async def test_paused_jobs_wait(queue: Queue, admin: Conn, pause: str) -> None:
    job_id = await queue.schedule(NewJob("alpha", "record", guild_id=SHARD0_GUILD))
    runnable = ["core", "alpha"]
    if pause == "plugin not loaded":
        runnable = ["core"]
    elif pause == "plugin disabled":
        await admin.execute("UPDATE core.guild_plugins SET enabled = false WHERE guild_id = $1", SHARD0_GUILD)
    else:
        await admin.execute("INSERT INTO core.guilds (guild_id, removed_at) VALUES ($1, now())", SHARD0_GUILD)
    assert await queue.claim(runnable, None) is None
    assert (await job_state(admin, job_id))["state"] == "pending"


async def test_core_jobs_run_for_a_server_the_bot_left(queue: Queue, admin: Conn) -> None:
    await admin.execute("INSERT INTO core.guilds (guild_id, removed_at) VALUES ($1, now())", SHARD0_GUILD)
    job_id = await queue.schedule(NewJob("core", "purge_guild", guild_id=SHARD0_GUILD))
    job = await queue.claim(["core"], None)
    assert job is not None and job.id == job_id


async def test_shard_filter_is_computed_from_the_guild(queue: Queue) -> None:
    on_one = await queue.schedule(NewJob("alpha", "x", guild_id=SHARD1_GUILD))
    await queue.schedule(NewJob("alpha", "x", guild_id=SHARD0_GUILD))
    job = await queue.claim(["alpha"], ShardFilter(shard_count=2, shard_ids=(1,)))
    assert job is not None and job.id == on_one
    assert await queue.claim(["alpha"], ShardFilter(shard_count=2, shard_ids=(1,))) is None
    assert await queue.claim(["alpha"], ShardFilter(shard_count=1, shard_ids=(0,))) is not None


async def test_one_running_apply_per_server(queue: Queue, admin: Conn) -> None:
    first = await queue.schedule(NewJob("core", "apply", guild_id=SHARD0_GUILD))
    second = await queue.schedule(NewJob("core", "apply", guild_id=SHARD0_GUILD))
    claimed = await queue.claim(["core"], None)
    assert claimed is not None and claimed.id == first
    assert await queue.claim(["core"], None) is None
    assert await job_state(admin, second) == {
        "state": "pending",
        "attempts": 0,
        "last_error": None,
        "later": True,
    }
    other = await queue.schedule(NewJob("core", "apply", guild_id=SHARD1_GUILD))
    claimed_other = await queue.claim(["core"], None)
    assert claimed_other is not None and claimed_other.id == other


async def test_failures_retry_with_back_off_then_fail(queue: Queue, admin: Conn) -> None:
    async def boom(_ctx: JobContext) -> None:
        raise RuntimeError("nope")

    queue.register("alpha", "boom", boom)
    job_id = await queue.schedule(NewJob("alpha", "boom", guild_id=SHARD0_GUILD))
    await admin.execute("UPDATE core.jobs SET max_attempts = 2 WHERE id = $1", job_id)
    workers = Workers(queue, lambda: ["alpha"])
    assert await workers.run_once()
    assert await job_state(admin, job_id) == {
        "state": "pending",
        "attempts": 1,
        "last_error": "RuntimeError('nope')",
        "later": True,
    }
    await admin.execute("UPDATE core.jobs SET run_at = now() WHERE id = $1", job_id)
    assert await workers.run_once()
    assert (await job_state(admin, job_id))["state"] == "failed"


async def test_a_job_with_no_handler_fails_with_a_reason(queue: Queue, admin: Conn) -> None:
    job_id = await queue.schedule(NewJob("alpha", "missing", guild_id=SHARD0_GUILD))
    await Workers(queue, lambda: ["alpha"]).run_once()
    assert (await job_state(admin, job_id))["last_error"] == "no handler alpha.missing"


async def test_an_expired_lease_is_reclaimed(queue: Queue, admin: Conn) -> None:
    job_id = await queue.schedule(NewJob("alpha", "x", guild_id=SHARD0_GUILD))
    assert await queue.claim(["alpha"], None) is not None
    assert await queue.claim(["alpha"], None) is None
    await admin.execute(
        "UPDATE core.jobs SET lease_until = now() - interval '1 second' WHERE id = $1", job_id
    )
    again = await queue.claim(["alpha"], None)
    assert again is not None and again.id == job_id and again.attempt == 2


async def test_a_plugin_scheduled_job_wakes_idle_workers(
    queue: Queue, pools: Pools, owner_login: Login
) -> None:
    done = asyncio.Event()

    async def ping(_ctx: JobContext) -> None:
        done.set()

    queue.register("alpha", "ping", ping)
    workers = Workers(queue, lambda: ["alpha"], count=1, poll_seconds=30)
    lock = await open_lock_connection(owner_login, lambda: None)
    await lock.conn.add_listener(NOTIFY_CHANNEL, workers.on_notify)
    workers.start()
    await asyncio.sleep(0.2)
    started = time.monotonic()
    await pools.plugin_db("alpha").fetchval("SELECT schedule_job($1, $2)", SHARD0_GUILD, "ping")
    await asyncio.wait_for(done.wait(), timeout=5)
    assert time.monotonic() - started < 2
    await workers.stop()
    await lock.close()


async def test_progress_is_recorded_and_finished_jobs_are_done(queue: Queue, admin: Conn) -> None:
    async def steps(ctx: JobContext) -> None:
        await ctx.report({"done": 3, "of": 3})

    queue.register("alpha", "steps", steps)
    job_id = await queue.schedule(NewJob("alpha", "steps", guild_id=SHARD0_GUILD))
    await Workers(queue, lambda: ["alpha"]).run_once()
    row = await admin.fetchrow("SELECT state, progress FROM core.jobs WHERE id = $1", job_id)
    assert row is not None and row["state"] == "done" and json.loads(row["progress"]) == {"done": 3, "of": 3}


async def test_maintenance_is_seeded_once(queue: Queue, admin: Conn) -> None:
    await seed_maintenance(queue.db, queue)
    await seed_maintenance(queue.db, queue)
    count = await admin.fetchval("SELECT count(*) FROM core.jobs WHERE handler = 'maintenance'")
    assert count == 1


class CountingQueue(Queue):
    """A queue that counts claims, and can be told to fail every claim."""

    def __init__(self, base: Queue, *, broken: bool = False) -> None:
        super().__init__(base.db, base.lease)
        self.claims = 0
        self.broken = broken

    async def claim(self, runnable_plugins: Sequence[str], shards: ShardFilter | None) -> Job | None:
        self.claims += 1
        if self.broken:
            raise RuntimeError("database down")
        return await super().claim(runnable_plugins, shards)


@pytest.mark.parametrize("broken", [False, True], ids=["idle", "failing"])
async def test_idle_or_failing_workers_wait_between_polls(queue: Queue, broken: bool) -> None:
    counting = CountingQueue(queue, broken=broken)
    workers = Workers(counting, lambda: ["alpha"], count=1, poll_seconds=0.2)
    workers.start()
    await asyncio.sleep(0.5)
    await workers.stop()
    assert 1 <= counting.claims <= 4


async def test_a_backlog_drains_without_waiting_for_the_poll(queue: Queue, admin: Conn) -> None:
    ran: list[int] = []

    async def note(ctx: JobContext) -> None:
        ran.append(ctx.job.id)

    queue.register("alpha", "note", note)
    for _ in range(3):
        await admin.execute(
            "INSERT INTO core.jobs (guild_id, plugin_id, handler) VALUES ($1, 'alpha', 'note')", SHARD0_GUILD
        )
    workers = Workers(queue, lambda: ["alpha"], count=1, poll_seconds=30)
    workers.start()
    await asyncio.sleep(0.5)
    await workers.stop()
    assert len(ran) == 3


async def test_a_long_job_keeps_its_lease(admin: Conn, pools: Pools, queue: Queue) -> None:
    short = Queue(pools.core_db(), lease=timedelta(milliseconds=300))
    release = asyncio.Event()

    async def slow(_ctx: JobContext) -> None:
        await release.wait()

    short.register("alpha", "slow", slow)
    await short.schedule(NewJob("alpha", "slow", guild_id=SHARD0_GUILD))
    workers = Workers(short, lambda: ["alpha"], count=1, poll_seconds=30)
    workers.start()
    await asyncio.sleep(1.0)
    stolen = await short.claim(["alpha"], None)
    release.set()
    await asyncio.sleep(0.2)
    await workers.stop()
    assert stolen is None


async def test_a_job_can_carry_its_own_attempt_limit(queue: Queue, admin: Conn) -> None:
    default = await queue.schedule(NewJob("alpha", "x", guild_id=SHARD0_GUILD))
    patient = await queue.schedule(NewJob("alpha", "x", guild_id=SHARD0_GUILD, max_attempts=48))
    limits = {r["id"]: r["max_attempts"] for r in await admin.fetch("SELECT id, max_attempts FROM core.jobs")}
    assert (limits[default], limits[patient]) == (5, 48)


async def test_a_job_for_no_server_is_claimed_by_any_shard(queue: Queue) -> None:
    await queue.schedule(NewJob("core", "maintenance"))
    job = await queue.claim(["core"], ShardFilter(shard_count=2, shard_ids=(1,)))
    assert job is not None and job.guild_id is None
