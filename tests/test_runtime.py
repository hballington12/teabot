"""The runner's orchestration (WP1.7), with real pools, lock connection and workers, and fake Discord and HTTP."""

import asyncio
import json
from typing import Any

import pytest

from teabot.core.processes import ShardOwnedError, open_lock_connection
from teabot.core.queue import Queue
from teabot.core.worker import Workers
from teabot.db.migrate import migrate
from teabot.db.naming import Naming
from teabot.db.pool import Login, Pools
from teabot.db.types import Conn
from teabot.runtime import Runtime, serve_until_stopped


class FakeClient:
    """Stands in for discord.py: locks its shards and runs until closed, or fails to lock.

    With `ends_with`, `start` returns when that event is set, as discord.py's does when it is closed.
    """

    def __init__(
        self, *, error: Exception | None = None, locks: bool = True, ends_with: asyncio.Event | None = None
    ) -> None:
        self._locked = asyncio.Event()
        self.error = error
        self.locks = locks
        self.ends_with = ends_with or asyncio.Event()
        self.closed = False

    async def wait_for_shards(self) -> int:
        await self._locked.wait()
        return 2

    async def start(self, token: str) -> None:
        assert token == "token"
        if self.error is not None:
            raise self.error
        if self.locks:
            self._locked.set()
        await self.ends_with.wait()

    async def close(self) -> None:
        self.closed = True


class FakeServer:
    """Stands in for uvicorn: serves until asked to exit, or fails at once."""

    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.started = False
        self.finished = False
        self.serving = asyncio.Event()
        self._exit = asyncio.Event()

    @property
    def should_exit(self) -> bool:
        return self._exit.is_set()

    @should_exit.setter
    def should_exit(self, value: bool) -> None:
        if value:
            self._exit.set()

    async def serve(self) -> None:
        self.started = True
        if self.error is not None:
            raise self.error
        self.serving.set()
        await self._exit.wait()
        self.finished = True


@pytest.fixture
async def parts(admin: Conn, naming: Naming, pools: Pools, owner_login: Login) -> Any:
    await migrate(admin, naming, [])
    stop, failed = asyncio.Event(), list[str]()

    def lost() -> None:
        failed.append("lock connection lost")
        stop.set()

    lock = await open_lock_connection(owner_login, lost)
    workers = Workers(Queue(pools.core_db()), lambda: ["core"])
    return pools, lock, workers, stop, failed


def runtime(parts: Any, client: FakeClient, server: FakeServer) -> Runtime:
    pools, lock, workers, stop, failed = parts
    statuses = {"alpha": "loaded", "beta": "blocked"}
    return Runtime(
        "token",
        "9.9",
        pools,
        lock,
        workers,
        client,
        server,
        plugin_statuses=statuses,
        stop=stop,
        failed=failed,
    )


async def process_rows(admin: Conn) -> int:
    count: int = await admin.fetchval("SELECT count(*) FROM core.processes")
    return count


async def test_a_refused_shard_lock_fails_without_serving_or_working(parts: Any, admin: Conn) -> None:
    server = FakeServer()
    rt = runtime(parts, FakeClient(error=ShardOwnedError("shard 0 is already run")), server)
    assert await serve_until_stopped(rt) == 1
    assert "discord stopped: ShardOwnedError('shard 0 is already run')" in rt.failed
    assert not server.started
    assert await process_rows(admin) == 0


async def test_a_requested_stop_shuts_down_cleanly(parts: Any, admin: Conn) -> None:
    client, server = FakeClient(), FakeServer()
    rt = runtime(parts, client, server)
    running = asyncio.create_task(serve_until_stopped(rt))
    await asyncio.wait_for(server.serving.wait(), timeout=5)
    assert await process_rows(admin) == 1
    rt.stop.set()
    assert await asyncio.wait_for(running, timeout=10) == 0
    assert server.finished and client.closed and not rt.failed
    assert await process_rows(admin) == 0
    assert parts[1].conn.is_closed()


async def test_a_lost_lock_connection_stops_with_a_failure(parts: Any, admin: Conn) -> None:
    server = FakeServer()
    rt = runtime(parts, FakeClient(), server)
    running = asyncio.create_task(serve_until_stopped(rt))
    await asyncio.wait_for(server.serving.wait(), timeout=5)
    await admin.execute("SELECT pg_terminate_backend($1)", parts[1].conn.get_server_pid())
    assert await asyncio.wait_for(running, timeout=10) == 1
    assert rt.failed == ["lock connection lost"]


async def test_an_http_failure_stops_with_its_reason(parts: Any) -> None:
    rt = runtime(parts, FakeClient(), FakeServer(error=OSError("address in use")))
    assert await serve_until_stopped(rt) == 1
    assert rt.failed == ["work stopped: OSError('address in use')"]


async def test_a_stop_before_the_shards_lock_never_serves(parts: Any) -> None:
    server = FakeServer()
    rt = runtime(parts, FakeClient(locks=False), server)
    running = asyncio.create_task(serve_until_stopped(rt))
    await asyncio.sleep(0.2)
    rt.stop.set()
    assert await asyncio.wait_for(running, timeout=10) == 0
    assert not server.started


async def test_a_part_ending_with_a_requested_stop_is_not_a_failure(parts: Any) -> None:
    pools, lock, workers, stop, failed = parts
    server = FakeServer()
    rt = Runtime(
        "token", "9.9", pools, lock, workers, FakeClient(ends_with=stop), server, stop=stop, failed=failed
    )
    running = asyncio.create_task(serve_until_stopped(rt))
    await asyncio.wait_for(server.serving.wait(), timeout=5)
    stop.set()
    assert await asyncio.wait_for(running, timeout=10) == 0
    assert rt.failed == []


async def test_the_process_row_records_the_locked_shards(parts: Any, admin: Conn) -> None:
    server = FakeServer()
    rt = runtime(parts, FakeClient(), server)
    running = asyncio.create_task(serve_until_stopped(rt))
    await asyncio.wait_for(server.serving.wait(), timeout=5)
    row = await admin.fetchrow("SELECT shard_ids, shard_count, version, plugins FROM core.processes")
    rt.stop.set()
    await asyncio.wait_for(running, timeout=10)
    assert row is not None
    assert (row["shard_ids"], row["shard_count"], row["version"]) == ([0, 1], 2, "9.9")
    assert json.loads(row["plugins"]) == {"alpha": "loaded", "beta": "blocked"}
