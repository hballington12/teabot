"""Shard and plugin locks, and the process row (WP1.5)."""

import asyncio
from typing import Any

import pytest

from teapot.core.processes import (
    LockConnection,
    ProcessIdentity,
    ShardOwnedError,
    delete_process_row,
    loaded_plugins,
    open_lock_connection,
    write_process_row,
)
from teapot.db.lockkeys import PLUGIN_NS, objid_to_key, plugin_key
from teapot.db.migrate import migrate
from teapot.db.naming import Naming
from teapot.db.pool import Login, Pools
from teapot.db.types import Conn


@pytest.fixture
async def migrated(admin: Conn, naming: Naming, pools: Pools) -> Pools:
    await migrate(admin, naming, [])
    return pools


@pytest.fixture
async def lock_pair(owner_login: Login) -> Any:
    lost: list[str] = []
    a = await open_lock_connection(owner_login, lambda: lost.append("a"))
    b = await open_lock_connection(owner_login, lambda: lost.append("b"))
    yield a, b, lost
    await a.close()
    await b.close()


def test_plugin_key_round_trips_through_pg_locks_form() -> None:
    key = plugin_key("announcements")
    assert objid_to_key(key % 2**32) == key


async def test_second_process_cannot_take_a_shard(
    lock_pair: tuple[LockConnection, LockConnection, list[str]],
) -> None:
    a, b, _ = lock_pair
    await a.take_shards([0, 1])
    with pytest.raises(ShardOwnedError):
        await b.take_shards([2, 1])
    held_by_b = await b.conn.fetchval(
        "SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid() AND locktype = 'advisory'"
    )
    assert held_by_b == 0


async def test_killed_connection_frees_shards_and_reports(
    lock_pair: tuple[LockConnection, LockConnection, list[str]], admin: Conn
) -> None:
    a, b, lost = lock_pair
    await a.take_shards([0])
    await admin.execute("SELECT pg_terminate_backend($1)", a.conn.get_server_pid())
    await asyncio.sleep(0.2)
    assert lost == ["a"]
    await b.take_shards([0])


async def test_plugin_locks_block_purge(
    lock_pair: tuple[LockConnection, LockConnection, list[str]], admin: Conn
) -> None:
    a, b, _ = lock_pair
    assert await a.take_plugins(["alpha"]) == []
    assert await b.take_plugins(["alpha"]) == []
    key = plugin_key("alpha")
    assert await admin.fetchval("SELECT pg_try_advisory_lock($1, $2)", PLUGIN_NS, key) is False
    await a.release_plugin("alpha")
    await b.release_plugin("alpha")
    assert await admin.fetchval("SELECT pg_try_advisory_lock($1, $2)", PLUGIN_NS, key) is True
    assert await a.take_plugins(["alpha", "beta"]) == ["alpha"]


async def test_loaded_plugins_reads_pg_locks(
    lock_pair: tuple[LockConnection, LockConnection, list[str]], migrated: Pools
) -> None:
    a, _, _ = lock_pair
    await a.take_plugins(["alpha", "announcements"])
    found = await loaded_plugins(migrated.core_db(), ["alpha", "announcements", "beta"])
    assert found == {"alpha", "announcements"}


async def test_process_row_is_written_and_deleted(migrated: Pools) -> None:
    db = migrated.core_db()
    identity = ProcessIdentity(shard_ids=(0,), shard_count=1, version="0.1")
    await write_process_row(db, identity, {"alpha": "loaded"})
    await write_process_row(db, identity, {"alpha": "loaded", "beta": "failed"})
    row = await db.fetchrow(
        "SELECT shard_ids, plugins FROM core.processes WHERE process_id = $1", identity.process_id
    )
    assert row is not None and row["shard_ids"] == [0] and '"beta": "failed"' in row["plugins"]
    await delete_process_row(db, identity)
    assert await db.fetchval("SELECT count(*) FROM core.processes") == 0


def test_the_unsigned_boundary_maps_to_the_most_negative_key() -> None:
    assert objid_to_key(2**31) == -(2**31)
    assert objid_to_key(2**31 - 1) == 2**31 - 1


async def test_close_closes_the_lock_connection(owner_login: Login, admin: Conn) -> None:
    lock = await open_lock_connection(owner_login, lambda: None)
    await lock.close()
    assert lock.conn.is_closed()
    killed = await open_lock_connection(owner_login, lambda: None)
    await admin.execute("SELECT pg_terminate_backend($1)", killed.conn.get_server_pid())
    await asyncio.sleep(0.2)
    await killed.close()
