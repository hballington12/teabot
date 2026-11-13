"""Shard and plugin ownership through advisory locks, and the informational process row (D40, spike S2).

The locks live on one dedicated connection outside any pool, because asyncpg's pool reset releases every
advisory lock and `LISTEN` a pooled connection holds. A crash releases them at once.
"""

import json
import logging
import socket
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from teapot.db.lockkeys import PLUGIN_NS, SHARD_NS, objid_to_key, plugin_key
from teapot.db.pool import Database, Login, connect
from teapot.db.types import Conn

log = logging.getLogger(__name__)

LOADED_PLUGIN_LOCKS = """
SELECT objid FROM pg_locks
WHERE locktype = 'advisory' AND classid = $1 AND objsubid = 2 AND mode = 'ShareLock' AND granted
  AND database = (SELECT oid FROM pg_database WHERE datname = current_database())
"""


class ShardOwnedError(RuntimeError):
    """Another live process already runs one of these shards on the same bot token."""


@dataclass
class ProcessIdentity:
    shard_ids: tuple[int, ...]
    shard_count: int
    version: str
    process_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    host: str = field(default_factory=socket.gethostname)


class LockConnection:
    """The process's lock connection: shard locks, plugin locks and `LISTEN`."""

    def __init__(self, conn: Conn, on_lost: Callable[[], None]) -> None:
        self.conn = conn
        self._on_lost = on_lost
        conn.add_termination_listener(self._terminated)

    def _terminated(self, _conn: object) -> None:
        log.critical("lock connection lost; shard and plugin locks are gone")
        self._on_lost()

    async def take_shards(self, shard_ids: Iterable[int]) -> None:
        """Lock every shard, or release them all and raise if any is taken."""
        taken: list[int] = []
        for shard_id in shard_ids:
            if await self.conn.fetchval("SELECT pg_try_advisory_lock($1, $2)", SHARD_NS, shard_id):
                taken.append(shard_id)
                continue
            for done in taken:
                await self.conn.execute("SELECT pg_advisory_unlock($1, $2)", SHARD_NS, done)
            raise ShardOwnedError(f"shard {shard_id} is already run by another process on this bot token")

    async def take_plugins(self, plugin_ids: Iterable[str]) -> list[str]:
        """Take a shared lock per plugin. Returns the ids a purge holds, which must not be loaded."""
        blocked: list[str] = []
        for plugin_id in plugin_ids:
            if not await self.conn.fetchval(
                "SELECT pg_try_advisory_lock_shared($1, $2)", PLUGIN_NS, plugin_key(plugin_id)
            ):
                blocked.append(plugin_id)
        return blocked

    async def release_plugin(self, plugin_id: str) -> None:
        await self.conn.execute("SELECT pg_advisory_unlock_shared($1, $2)", PLUGIN_NS, plugin_key(plugin_id))

    async def close(self) -> None:
        self.conn.remove_termination_listener(self._terminated)
        if not self.conn.is_closed():
            await self.conn.close()


async def open_lock_connection(login: Login, on_lost: Callable[[], None]) -> LockConnection:
    return LockConnection(await connect(login), on_lost)


async def loaded_plugins(db: Database, known_ids: Iterable[str]) -> set[str]:
    """The known plugins that some process holds a shared lock on, read from `pg_locks`."""
    by_key = {plugin_key(p): p for p in known_ids}
    rows = await db.fetch(LOADED_PLUGIN_LOCKS, PLUGIN_NS)
    return {by_key[k] for r in rows if (k := objid_to_key(int(r["objid"]))) in by_key}


async def write_process_row(db: Database, identity: ProcessIdentity, plugin_statuses: dict[str, str]) -> None:
    await db.execute(
        """
        INSERT INTO core.processes (process_id, host, shard_ids, shard_count, version, plugins)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
        ON CONFLICT (process_id) DO UPDATE
        SET shard_ids = EXCLUDED.shard_ids, shard_count = EXCLUDED.shard_count,
            plugins = EXCLUDED.plugins, updated_at = now()
        """,
        identity.process_id,
        identity.host,
        list(identity.shard_ids),
        identity.shard_count,
        identity.version,
        json.dumps(plugin_statuses),
    )


async def delete_process_row(db: Database, identity: ProcessIdentity) -> None:
    await db.execute("DELETE FROM core.processes WHERE process_id = $1", identity.process_id)


async def delete_stale_process_rows(db: Database, minutes: int = 10) -> str:
    return await db.execute(
        "DELETE FROM core.processes WHERE updated_at < now() - make_interval(mins => $1)", minutes
    )


def shard_ids_for(shard_count: int, owned: Sequence[int] | None = None) -> tuple[int, ...]:
    """All shards, unless a cluster runs only some of them (D40)."""
    return tuple(owned) if owned is not None else tuple(range(shard_count))
