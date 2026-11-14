"""Queue workers (D31): claim, run under a lease, record the outcome, and sleep until woken or due."""

import asyncio
import contextlib
import logging
from collections.abc import Callable, Sequence

from teabot.core.queue import Job, JobContext, NewJob, Queue, ShardFilter
from teabot.db.pool import Database

log = logging.getLogger(__name__)

MAINTENANCE_PENDING = """
SELECT 1 FROM core.jobs
WHERE plugin_id = 'core' AND handler = 'maintenance' AND state IN ('pending', 'running')
"""


class Workers:
    """A small pool of workers sharing one queue. `wake()` is safe to call from any callback."""

    def __init__(
        self,
        queue: Queue,
        runnable_plugins: Callable[[], Sequence[str]],
        shards: ShardFilter | None = None,
        *,
        count: int = 8,
        poll_seconds: float = 5.0,
    ) -> None:
        self.queue = queue
        self.runnable_plugins = runnable_plugins
        self.shards = shards
        self.count = count
        self.poll_seconds = poll_seconds
        self._event = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        queue.wake = self.wake

    def wake(self) -> None:
        self._event.set()

    def on_notify(self, *_args: object) -> None:
        """A `LISTEN` callback for the lock connection."""
        self.wake()

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._loop(), name=f"teabot-worker-{i}") for i in range(self.count)
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []

    async def _loop(self) -> None:
        while True:
            try:
                ran = await self.run_once()
            except Exception:
                log.exception("queue worker error")
                ran = False
            if not ran:
                await self._sleep()

    async def _sleep(self) -> None:
        due = await self.queue.seconds_until_next(self.runnable_plugins())
        timeout = self.poll_seconds if due is None else min(due, self.poll_seconds)
        self._event.clear()
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(self._event.wait(), timeout=timeout)

    async def run_once(self) -> bool:
        """Claim and run one job. Returns False when nothing was due."""
        job = await self.queue.claim(self.runnable_plugins(), self.shards)
        if job is None:
            return False
        await self._run(job)
        return True

    async def _run(self, job: Job) -> None:
        handler = self.queue.handlers.get((job.plugin_id, job.handler))
        if handler is None:
            await self.queue.fail(job, f"no handler {job.plugin_id}.{job.handler}")
            return
        keeper = asyncio.create_task(self._keep_lease(job))
        try:
            await handler(JobContext(job, self.queue.db))
        except Exception as exc:
            log.warning(
                "job %s.%s failed: %r",
                job.plugin_id,
                job.handler,
                exc,
                exc_info=exc,
                extra={"job_id": job.id, "handler": job.handler, "error": repr(exc)},
            )
            await self.queue.fail(job, repr(exc))
        else:
            await self.queue.finish(job)
        finally:
            keeper.cancel()

    async def _keep_lease(self, job: Job) -> None:
        interval = self.queue.lease.total_seconds() / 3
        while True:
            await asyncio.sleep(interval)
            await self.queue.extend_lease(job)


async def seed_maintenance(db: Database, queue: Queue) -> None:
    """Make sure one maintenance job is pending. The handler reschedules itself."""
    exists = await db.fetchval(MAINTENANCE_PENDING)
    if not exists:
        await queue.schedule(NewJob("core", "maintenance"))
