"""The core and plugin pools, transaction handles and query helpers (D30, spike S1).

- Every helper runs one statement through Postgres's extended protocol. asyncpg's `execute` without
  arguments would use the simple protocol, which runs several statements, so it is never called that way.
- A plugin connection switches to the plugin's role and schema when acquired, and runs `RESET ROLE` on
  release, because asyncpg's own reset leaves the role in place.
- Inside `async with db.transaction() as tx:`, plugin code goes through `tx`. Calling the plugin's `db`
  there raises, because it would take another connection and miss the block's writes.
"""

import logging
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import asyncpg

from teapot.db.naming import Naming
from teapot.db.types import AnyConn, Conn, Pool, Record

log = logging.getLogger(__name__)

_open_block: ContextVar[str | None] = ContextVar("teapot_open_block", default=None)


class BlockOpenError(RuntimeError):
    """`db` was used inside its own open transaction block, where `tx` must be used."""


async def _execute(conn: AnyConn, query: str, args: tuple[Any, ...]) -> str:
    if args:
        return await conn.execute(query, *args)
    stmt = await conn.prepare(query)
    await stmt.fetch()
    return stmt.get_statusmsg() or ""


class Queries:
    """The query helpers shared by `Database` and `Transaction`."""

    @asynccontextmanager
    async def _connection(self) -> AsyncGenerator[AnyConn]:
        raise NotImplementedError
        yield  # pragma: no cover

    async def execute(self, query: str, *args: Any) -> str:
        """Run one statement and return its status, such as `INSERT 0 1`."""
        async with self._connection() as conn:
            return await _execute(conn, query, args)

    async def fetch(self, query: str, *args: Any) -> list[Record]:
        async with self._connection() as conn:
            return await conn.fetch(query, *args)

    async def fetchrow(self, query: str, *args: Any) -> Record | None:
        async with self._connection() as conn:
            return await conn.fetchrow(query, *args)

    async def fetchval(self, query: str, *args: Any) -> Any:
        async with self._connection() as conn:
            return await conn.fetchval(query, *args)


class Transaction(Queries):
    """The handle inside a transaction block. Every call uses the block's connection."""

    def __init__(self, conn: AnyConn) -> None:
        self.connection = conn

    @asynccontextmanager
    async def _connection(self) -> AsyncGenerator[AnyConn]:
        yield self.connection


@dataclass(frozen=True)
class Timing:
    """When a transaction counts as slow, and the clock that measures it. Tests pass their own clock."""

    slow_ms: float | None = None
    clock: Callable[[], float] = time.perf_counter


class Database(Queries):
    """Query helpers over a pool, acting as the core. `PluginDatabase` acts as one plugin."""

    def __init__(self, pool: Pool, name: str = "core", timing: Timing | None = None) -> None:
        self.pool = pool
        self.name = name
        self.timing = timing or Timing()

    @asynccontextmanager
    async def _connection(self) -> AsyncGenerator[AnyConn]:
        if _open_block.get() == self.name:
            raise BlockOpenError(f"{self.name}: use tx inside an open transaction block, not db")
        async with self.pool.acquire() as conn:
            yield conn

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[Transaction]:
        """Open a transaction on one pooled connection, committed on exit and rolled back on error."""
        async with self._connection() as conn:
            token = _open_block.set(self.name)
            started = self.timing.clock()
            try:
                async with conn.transaction():
                    yield Transaction(conn)
            finally:
                _open_block.reset(token)
                self._log_if_slow(started)

    def _log_if_slow(self, started: float) -> None:
        held_ms = (self.timing.clock() - started) * 1000
        if self.timing.slow_ms is not None and held_ms > self.timing.slow_ms:
            log.warning("slow transaction", extra={"scope": self.name, "held_ms": held_ms})


class PluginDatabase(Database):
    """Query helpers acting as one plugin: its role and its schema, reset on release (S1)."""

    def __init__(self, pool: Pool, name: str, naming: Naming, timing: Timing | None = None) -> None:
        super().__init__(pool, name, timing)
        self.role = naming.plugin_role(name)
        self.schema = naming.plugin_schema(name)

    @asynccontextmanager
    async def _connection(self) -> AsyncGenerator[AnyConn]:
        async with super()._connection() as conn:
            await conn.execute(f'SET ROLE "{self.role}"; SET search_path TO "{self.schema}"')
            try:
                yield conn
            finally:
                if not conn.is_closed():
                    await conn.execute("RESET ROLE; RESET search_path")


@dataclass
class Pools:
    """A process's two pools (D30): the core's as the app role, and plugins' as the plugins role."""

    core: Pool
    plugins: Pool
    naming: Naming
    timing: Timing = field(default_factory=Timing)

    def core_db(self) -> Database:
        return Database(self.core, "core", self.timing)

    def plugin_db(self, plugin_id: str) -> PluginDatabase:
        return PluginDatabase(self.plugins, plugin_id, self.naming, self.timing)

    async def close(self) -> None:
        await self.core.close()
        await self.plugins.close()


@dataclass(frozen=True)
class ConnectionInfo:
    host: str
    port: int
    database: str


@dataclass(frozen=True)
class Login:
    """Everything one direct connection needs: where, and as whom."""

    info: ConnectionInfo
    user: str
    password: str


async def connect(login: Login) -> Conn:
    """A single connection outside any pool, such as the lock connection (D40) or the migration runner."""
    return await asyncpg.connect(
        host=login.info.host,
        port=login.info.port,
        database=login.info.database,
        user=login.user,
        password=login.password,
    )


@dataclass(frozen=True)
class Credentials:
    """Passwords of the two login roles."""

    app_password: str
    plugins_password: str


async def create_pools(
    info: ConnectionInfo,
    naming: Naming,
    credentials: Credentials,
    *,
    size: int = 10,
    timing: Timing | None = None,
) -> Pools:
    """Open both pools. Each gets `size` connections at most."""
    core = await open_pool(Login(info, naming.app_role, credentials.app_password), size)
    plugins = await open_pool(Login(info, naming.plugins_role, credentials.plugins_password), size)
    return Pools(core, plugins, naming, timing or Timing())


async def open_pool(login: Login, size: int) -> Pool:
    """A pool that opens one connection up front and grows to `size`."""
    return await asyncpg.create_pool(
        host=login.info.host,
        port=login.info.port,
        database=login.info.database,
        user=login.user,
        password=login.password,
        min_size=1,
        max_size=size,
    )
