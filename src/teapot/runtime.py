"""The runner's orchestration (D40): supervise the gateway, the work and the process row, then shut down in order.

Nothing runs or serves until the client has locked its shards, so a second process on the same token never
does either. Any part ending before a requested stop ends the run as a failure with its reason. The Discord
client and the HTTP server are protocols here, so the orchestration is tested with real database parts and
fake Discord and HTTP; `teapot.app` wires the real ones.
"""

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from teapot.core.processes import LockConnection, ProcessIdentity, delete_process_row, write_process_row
from teapot.core.worker import Workers, seed_maintenance
from teapot.db.pool import Pools

log = logging.getLogger(__name__)


class GatewayClient(Protocol):
    """What the runtime needs from the Discord client."""

    async def wait_for_shards(self) -> int:
        """Return the shard count once the client has locked every shard, which it does before connecting."""
        ...

    async def start(self, token: str) -> None: ...

    async def close(self) -> None: ...


class HttpServer(Protocol):
    """What the runtime needs from the HTTP server: serve, report that it started, and exit when asked."""

    @property
    def started(self) -> bool: ...

    @property
    def should_exit(self) -> bool: ...

    @should_exit.setter
    def should_exit(self, value: bool) -> None: ...

    async def serve(self) -> None: ...


@dataclass
class Runtime:
    token: str
    version: str
    pools: Pools
    lock: LockConnection
    workers: Workers
    client: GatewayClient
    server: HttpServer
    process_row_every: float = 60.0
    identity: ProcessIdentity | None = None
    stop: asyncio.Event = field(default_factory=asyncio.Event)
    failed: list[str] = field(default_factory=list[str])


async def _work_once_locked(rt: Runtime) -> None:
    shard_count = await rt.client.wait_for_shards()
    rt.identity = ProcessIdentity(tuple(range(shard_count)), shard_count, rt.version)
    await write_process_row(rt.pools.core_db(), rt.identity, {})
    await seed_maintenance(rt.pools.core_db(), rt.workers.queue)
    rt.workers.start()
    await rt.server.serve()


async def _keep_process_row(rt: Runtime) -> None:
    while True:
        await asyncio.sleep(rt.process_row_every)
        if rt.identity is not None:
            await write_process_row(rt.pools.core_db(), rt.identity, {})


def _note_finished(rt: Runtime, task: asyncio.Task[Any]) -> None:
    if task.get_name() != "stop" and not rt.stop.is_set():
        error = None if task.cancelled() else task.exception()
        rt.failed.append(f"{task.get_name()} stopped: {error!r}" if error else f"{task.get_name()} stopped")
    rt.stop.set()


async def _supervise(rt: Runtime) -> asyncio.Task[None]:
    """Run until stop; return the work task, which shutdown lets finish serving instead of cancelling."""
    work = asyncio.create_task(_work_once_locked(rt), name="work")
    tasks: set[asyncio.Task[Any]] = {
        asyncio.create_task(rt.client.start(rt.token), name="discord"),
        work,
        asyncio.create_task(_keep_process_row(rt), name="process-row"),
        asyncio.create_task(rt.stop.wait(), name="stop"),
    }
    while not rt.stop.is_set():
        done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            _note_finished(rt, task)
    for task in tasks - {work}:
        task.cancel()
    return work


async def _stop_http(rt: Runtime, work: asyncio.Task[None]) -> None:
    """Ask the server to exit and wait for it; cancel only a work task that never got as far as serving.

    A work task that already ended has had its reason recorded, so it is not awaited again.
    """
    if work.done():
        return
    rt.server.should_exit = True
    if not rt.server.started:
        work.cancel()
    with contextlib.suppress(asyncio.CancelledError, TimeoutError):
        await asyncio.wait_for(work, timeout=10)


async def _shutdown(rt: Runtime, work: asyncio.Task[None] | None) -> None:
    await rt.workers.stop()
    if work is not None:
        await _stop_http(rt, work)
    await rt.client.close()
    if rt.identity is not None:
        await delete_process_row(rt.pools.core_db(), rt.identity)
    await rt.lock.close()


async def serve_until_stopped(rt: Runtime) -> int:
    """Run, then shut down. Returns the exit code: 0 for a requested stop, 1 for a failure."""
    work: asyncio.Task[None] | None = None
    try:
        work = await _supervise(rt)
    finally:
        await _shutdown(rt, work)
    for reason in rt.failed:
        log.error("teapot stopped", extra={"reason": reason})
    return 1 if rt.failed else 0
