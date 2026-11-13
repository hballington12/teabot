"""The core's maintenance job (D31, D40): prune finished jobs and stale process rows, then reschedule.

Deletes run in batches so a large backlog never holds a long transaction. Rescheduling skips when another
maintenance job is already pending, so a crash between the two steps never leaves two copies.
"""

from datetime import UTC, datetime, timedelta

from teapot.core.processes import delete_stale_process_rows
from teapot.core.queue import JobContext, NewJob, Queue

PRUNE_BATCH = """
DELETE FROM core.jobs WHERE id IN (
    SELECT id FROM core.jobs
    WHERE state IN ('done', 'failed', 'cancelled') AND finished_at < now() - make_interval(days => $1)
    LIMIT $2
)
"""
OTHER_PENDING = (
    "SELECT 1 FROM core.jobs WHERE plugin_id = 'core' AND handler = 'maintenance' AND state = 'pending'"
)
EVERY = timedelta(days=1)


class Maintenance:
    """The `core.maintenance` handler."""

    def __init__(self, queue: Queue, *, retention_days: int = 30, batch: int = 5000) -> None:
        self.queue = queue
        self.retention_days = retention_days
        self.batch = batch

    async def __call__(self, ctx: JobContext) -> None:
        await self._prune_jobs()
        await delete_stale_process_rows(self.queue.db)
        if not await self.queue.db.fetchval(OTHER_PENDING):
            await self.queue.schedule(NewJob("core", "maintenance", run_at=datetime.now(UTC) + EVERY))

    async def _prune_jobs(self) -> None:
        while await self.queue.db.execute(PRUNE_BATCH, self.retention_days, self.batch) != "DELETE 0":
            pass
