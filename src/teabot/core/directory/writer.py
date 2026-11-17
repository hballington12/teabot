"""The directory's writers (D55): one per shard, the only writer of member state.

Gateway events are offered as they arrive and never wait: a full queue drops the event and marks the shard, whose
servers are reconciled once a batch commits again. A reconcile's page waits for room. Each writer applies up to
`BATCH` events in one transaction, or one page alone, and retries a failed batch one entry at a time, so one bad
event is logged and skipped instead of stalling its shard.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from teabot.core.directory.apply import Apply
from teabot.core.directory.inbox import Entry, Page
from teabot.db.pool import Database

log = logging.getLogger(__name__)

LIMIT = 10_000
BATCH = 100
DRAIN_SECONDS = 10.0

type Dropped = Callable[[int], Awaitable[None]]


async def _nothing(_shard_id: int) -> None:
    return None


class Writer:
    """One shard's queue and the task that drains it."""

    def __init__(
        self, shard_id: int, db: Database, apply: Apply, *, limit: int = LIMIT, on_dropped: Dropped = _nothing
    ) -> None:
        self.shard_id = shard_id
        self.db = db
        self.apply = apply
        self.queue: asyncio.Queue[Entry] = asyncio.Queue(limit)
        self.dropped = 0
        self.on_dropped = on_dropped
        self._task: asyncio.Task[None] | None = None
        # A page taken off the queue while filling a batch, which goes in a batch of its own next.
        self._held: Entry | None = None

    def offer(self, entry: Entry) -> None:
        """Queue a gateway event, or drop it when the queue is full."""
        try:
            self.queue.put_nowait(entry)
        except asyncio.QueueFull:
            if not self.dropped:
                log.warning(
                    "directory events dropped: the writer is behind", extra={"shard_id": self.shard_id}
                )
            self.dropped += 1

    async def put(self, entry: Entry) -> None:
        """Queue a reconcile's entry, waiting for room: it is never dropped."""
        await self.queue.put(entry)

    async def submit(self, page: Page) -> None:
        """Queue a reconcile's page, waiting for room, and return once it is applied."""
        await self.queue.put(page)
        await page.done

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name=f"directory-writer-{self.shard_id}")

    async def close(self, seconds: float = DRAIN_SECONDS) -> None:
        """Wait for the queue to empty, up to `seconds`, then stop. What is left counts as dropped."""
        if self._task is None:
            return
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(seconds):
                await self.queue.join()
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        left = self.queue.qsize()
        if left:
            log.warning(
                "directory events dropped at shutdown", extra={"shard_id": self.shard_id, "count": left}
            )
        self._task = None

    async def _run(self) -> None:
        while True:
            batch = await self._next()
            try:
                await self.write(batch)
            finally:
                for _ in batch:
                    self.queue.task_done()

    async def _next(self) -> list[Entry]:
        """The next batch: one page alone, or up to `BATCH` events, stopping before a page."""
        first = self._held or await self.queue.get()
        self._held = None
        batch = [first]
        if isinstance(first, Page):
            return batch
        while len(batch) < BATCH and not self.queue.empty():
            entry = self.queue.get_nowait()
            if isinstance(entry, Page):
                self._held = entry
                break
            batch.append(entry)
        return batch

    async def write(self, batch: list[Entry]) -> None:
        """Apply a batch in one transaction, or one entry at a time when that fails."""
        self.apply.waiting.expire(datetime.now(UTC))
        try:
            async with self.db.transaction() as tx:
                for entry in batch:
                    await self.apply.one(tx, entry)
        except Exception:
            if len(batch) == 1:
                self._failed(batch[0])
                return
            for entry in batch:
                await self.write([entry])
            return
        for entry in batch:
            if isinstance(entry, Page) and not entry.done.done():
                entry.done.set_result(None)
        if self.dropped:
            self.dropped = 0
            await self.on_dropped(self.shard_id)

    def _failed(self, entry: Entry) -> None:
        """Skip an entry that cannot be applied. A skipped event counts as dropped, so its shard is reconciled."""
        self.dropped += 1
        log.exception(
            "directory entry skipped", extra={"shard_id": self.shard_id, "entry": type(entry).__name__}
        )
        if isinstance(entry, Page) and not entry.done.done():
            entry.done.set_exception(RuntimeError("the directory could not apply a reconcile's page"))
