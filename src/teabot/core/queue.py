"""The durable work queue (D31): jobs as rows, claimed with `SKIP LOCKED` and run under a lease.

A job runs only when its plugin is loaded and, for a server's job, when the plugin is enabled there and
the bot has not left the server. Other jobs wait in `pending`. The shard filter is computed from `guild_id`
at claim time and never stored, so resharding leaves nothing stale. A job for no server runs on any shard.
"""

import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import asyncpg

from teabot.db.pool import Database, Queries
from teabot.db.types import Record
from teabot.sdk.actions import JOB_TIMEOUT

log = logging.getLogger(__name__)

CORE = "core"
NOTIFY_CHANNEL = "teabot_jobs"
APPLY_HANDLER = "apply"
CLASH_DELAY = timedelta(seconds=5)
MAX_BACKOFF = timedelta(hours=1)

SELECT_DUE = """
SELECT j.id, j.state, j.attempts, j.max_attempts, j.plugin_id, j.handler FROM core.jobs j
WHERE ((j.state = 'pending' AND j.run_at <= now()) OR (j.state = 'running' AND j.lease_until < now()))
  AND j.plugin_id = ANY($1::text[])
  AND ($2::integer IS NULL OR j.guild_id IS NULL OR ((j.guild_id >> 22) % $2) = ANY($3::integer[]))
  AND (j.guild_id IS NULL OR j.plugin_id = 'core' OR (
        EXISTS (SELECT 1 FROM core.guild_plugins gp
                WHERE gp.guild_id = j.guild_id AND gp.plugin_id = j.plugin_id AND gp.enabled)
    AND NOT EXISTS (SELECT 1 FROM core.guilds g WHERE g.guild_id = j.guild_id AND g.removed_at IS NOT NULL)))
ORDER BY j.run_at
LIMIT 1
FOR UPDATE OF j SKIP LOCKED
"""

# A running job whose lease ran out was running when its process stopped. With its attempts used up, the job
# itself may be what stopped it, such as by blocking the loop or exhausting memory, so it is failed, not run again.
STOPPED = "the process stopped while running it"
MARK_STOPPED = """
UPDATE core.jobs SET state = 'failed', last_error = $2, finished_at = now(), lease_until = NULL WHERE id = $1
"""

MARK_RUNNING = """
UPDATE core.jobs SET state = 'running', attempts = attempts + 1, lease_until = now() + $2::interval
WHERE id = $1
RETURNING id, guild_id, plugin_id, handler, payload, attempts, max_attempts, started_by
"""


@dataclass(frozen=True)
class NewJob:
    """A job to queue, due now unless `run_at` says later. Queuing always wakes the workers,
    which then sleep until the earliest due job."""

    plugin_id: str
    handler: str
    guild_id: int | None = None
    run_at: datetime | None = None
    payload: dict[str, Any] = field(default_factory=dict[str, Any])
    started_by: int | None = None
    max_attempts: int = 5


@dataclass(frozen=True)
class Job:
    id: int
    guild_id: int | None
    plugin_id: str
    handler: str
    payload: dict[str, Any]
    attempt: int
    max_attempts: int
    started_by: int | None

    @classmethod
    def from_row(cls, row: Record) -> "Job":
        return cls(
            id=row["id"],
            guild_id=row["guild_id"],
            plugin_id=row["plugin_id"],
            handler=row["handler"],
            payload=json.loads(row["payload"]),
            attempt=row["attempts"],
            max_attempts=row["max_attempts"],
            started_by=row["started_by"],
        )


type Handler = Callable[["JobContext"], Awaitable[None]]


class JobContext:
    """What a handler receives: the job, and a way to report progress."""

    def __init__(self, job: Job, db: Database) -> None:
        self.job = job
        self._db = db

    async def report(self, progress: Mapping[str, Any]) -> None:
        await self._db.execute(
            "UPDATE core.jobs SET progress = $2::jsonb WHERE id = $1", self.job.id, json.dumps(dict(progress))
        )


@dataclass(frozen=True)
class ShardFilter:
    """The shards this process runs, or None for all of them."""

    shard_count: int
    shard_ids: tuple[int, ...]


class Queue:
    """Scheduling and claiming over the core database."""

    def __init__(self, db: Database, lease: timedelta = timedelta(seconds=60)) -> None:
        self.db = db
        self.lease = lease
        self.handlers: dict[tuple[str, str], Handler] = {}
        self.timeouts: dict[tuple[str, str], timedelta] = {}
        self.wake: Callable[[], None] = lambda: None

    def register(self, plugin_id: str, name: str, handler: Handler, timeout: timedelta = JOB_TIMEOUT) -> None:
        """Run `handler` for the plugin's jobs called `name`, each stopped once it takes longer than `timeout`."""
        self.handlers[(plugin_id, name)] = handler
        self.timeouts[(plugin_id, name)] = timeout

    async def schedule(self, job: NewJob, *, within: Queries | None = None) -> int:
        """Queue a job from core code. Plugins queue through their own `schedule_job` (D30).

        Pass `within` to queue inside an open transaction; the notification is then sent at its commit.
        """
        queries = within or self.db
        job_id: int = await queries.fetchval(
            """
            INSERT INTO core.jobs (guild_id, plugin_id, handler, run_at, payload, started_by, max_attempts)
            VALUES ($1, $2, $3, coalesce($4, now()), $5::jsonb, $6, $7) RETURNING id
            """,
            job.guild_id,
            job.plugin_id,
            job.handler,
            job.run_at,
            json.dumps(job.payload),
            job.started_by,
            job.max_attempts,
        )
        await queries.execute("SELECT pg_notify($1, $2)", NOTIFY_CHANNEL, str(job_id))
        self.wake()
        return job_id

    async def claim(self, runnable_plugins: Sequence[str], shards: ShardFilter | None) -> Job | None:
        """Claim one due job, or return None. A second running apply for a server is put back for later."""
        count = shards.shard_count if shards else None
        ids = list(shards.shard_ids) if shards else []
        while True:
            stopped, claimed = await self._claim_one(list(runnable_plugins), count, ids)
            if not stopped:
                return claimed

    async def _claim_one(
        self, plugins: list[str], count: int | None, ids: list[int]
    ) -> tuple[bool, Job | None]:
        """Claim the next due job. Returns whether the job found was failed instead, for having stopped its
        process on every attempt, and the job claimed."""
        async with self.db.transaction() as tx:
            due = await tx.fetchrow(SELECT_DUE, plugins, count, ids)
            if due is None:
                return False, None
            job_id = due["id"]
            if due["state"] == "running" and due["attempts"] >= due["max_attempts"]:
                await tx.execute(MARK_STOPPED, job_id, STOPPED)
                log.warning(
                    "job failed: its process stopped on every attempt",
                    extra={"job_id": job_id, "plugin": due["plugin_id"], "handler": due["handler"]},
                )
                return True, None
            try:
                async with tx.connection.transaction():
                    row = await tx.fetchrow(MARK_RUNNING, job_id, self.lease)
            except asyncpg.UniqueViolationError:
                await tx.execute(
                    "UPDATE core.jobs SET run_at = now() + $2::interval WHERE id = $1", job_id, CLASH_DELAY
                )
                return False, None
        return False, Job.from_row(row) if row is not None else None

    async def extend_lease(self, job: Job) -> None:
        await self.db.execute(
            "UPDATE core.jobs SET lease_until = now() + $2::interval WHERE id = $1 AND state = 'running'",
            job.id,
            self.lease,
        )

    async def finish(self, job: Job) -> None:
        await self.db.execute(
            "UPDATE core.jobs SET state = 'done', finished_at = now(), lease_until = NULL WHERE id = $1",
            job.id,
        )

    async def fail(self, job: Job, error: str) -> None:
        """Retry with exponential back-off, or mark failed once attempts run out."""
        if job.attempt >= job.max_attempts:
            await self.db.execute(
                "UPDATE core.jobs SET state = 'failed', last_error = $2, finished_at = now(), lease_until = NULL "
                "WHERE id = $1",
                job.id,
                error,
            )
            return
        delay = min(timedelta(seconds=2**job.attempt), MAX_BACKOFF)
        await self.db.execute(
            "UPDATE core.jobs SET state = 'pending', last_error = $2, run_at = now() + $3::interval, "
            "lease_until = NULL WHERE id = $1",
            job.id,
            error,
            delay,
        )

    async def seconds_until_next(self, runnable_plugins: Sequence[str]) -> float | None:
        wait: float | None = await self.db.fetchval(
            "SELECT extract(epoch FROM min(run_at) - now()) FROM core.jobs "
            "WHERE state = 'pending' AND plugin_id = ANY($1::text[])",
            list(runnable_plugins),
        )
        return None if wait is None else max(0.0, float(wait))
