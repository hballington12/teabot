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
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
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
class Scope:
    """Who a `Database` acts as: the core, or one plugin with its role and schema."""

    name: str
    role: str | None = None
    schema: str | None = None


class Database(Queries):
    """Query helpers over a pool, acting as the core or as one plugin."""

    def __init__(self, pool: Pool, scope: Scope, slow_ms: float | None = None) -> None:
        self.pool = pool
        self.scope = scope
        self.slow_ms = slow_ms

    @asynccontextmanager
    async def _connection(self) -> AsyncGenerator[AnyConn]:
        if self.scope.role is not None and _open_block.get() == self.scope.name:
            raise BlockOpenError(f"{self.scope.name}: use tx inside an open transaction block, not db")
        async with self.pool.acquire() as conn:
            await self._enter(conn)
            try:
                yield conn
            finally:
                await self._leave(conn)

    async def _enter(self, conn: AnyConn) -> None:
        if self.scope.role is not None:
            await conn.execute(f'SET ROLE "{self.scope.role}"; SET search_path TO "{self.scope.schema}"')

    async def _leave(self, conn: AnyConn) -> None:
        if self.scope.role is not None and not conn.is_closed():
            await conn.execute("RESET ROLE; RESET search_path")

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[Transaction]:
        """Open a transaction on one pooled connection, committed on exit and rolled back on error."""
        async with self._connection() as conn:
            token = _open_block.set(self.scope.name)
            started = time.perf_counter()
            try:
                async with conn.transaction():
                    yield Transaction(conn)
            finally:
                _open_block.reset(token)
                self._log_if_slow(started)

    def _log_if_slow(self, started: float) -> None:
        held_ms = (time.perf_counter() - started) * 1000
        if self.slow_ms is not None and held_ms > self.slow_ms:
            log.warning("slow transaction", extra={"scope": self.scope.name, "held_ms": round(held_ms, 1)})


@dataclass
class Pools:
    """A process's two pools (D30): the core's as the app role, and plugins' as the plugins role."""

    core: Pool
    plugins: Pool
    naming: Naming
    slow_ms: float | None = None

    def core_db(self) -> Database:
        return Database(self.core, Scope("core"), self.slow_ms)

    def plugin_db(self, plugin_id: str) -> Database:
        scope = Scope(plugin_id, self.naming.plugin_role(plugin_id), self.naming.plugin_schema(plugin_id))
        return Database(self.plugins, scope, self.slow_ms)

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
    slow_ms: float | None = None,
) -> Pools:
    """Open both pools. Each gets `size` connections at most."""

    async def make(user: str, password: str) -> Pool:
        return await asyncpg.create_pool(
            host=info.host,
            port=info.port,
            database=info.database,
            user=user,
            password=password,
            min_size=1,
            max_size=size,
        )

    core = await make(naming.app_role, credentials.app_password)
    plugins = await make(naming.plugins_role, credentials.plugins_password)
    return Pools(core, plugins, naming, slow_ms)
