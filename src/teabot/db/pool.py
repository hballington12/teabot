"""The core and plugin pools, transaction handles and query helpers (D30, spike S1).

- Every helper runs one statement through Postgres's extended protocol. asyncpg's `execute` without
  arguments would use the simple protocol, which runs several statements, so it is never called that way.
- A plugin connection switches to the plugin's role and schema when acquired, and runs `RESET ROLE` on
  release, because asyncpg's own reset leaves the role in place.
- Inside `async with db.transaction() as tx:`, plugin code goes through `tx`. Calling the plugin's `db`
  there raises, because it would take another connection and miss the block's writes.
"""

import json
import logging
import time
from collections.abc import AsyncGenerator, Callable, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import asyncpg
from pydantic import BaseModel, TypeAdapter

from teabot.db.naming import Naming
from teabot.db.types import AnyConn, Conn, Pool, Record
from teabot.sdk.db import Bound

log = logging.getLogger(__name__)

_open_block: ContextVar[str | None] = ContextVar("teabot_open_block", default=None)


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

    async def fetch(self, query: Any, *args: Any) -> list[Any]:
        """Every row; with a result type first, each row checked into it (`fetch(Model, sql, ...)`)."""
        kind, query, args = _typed(query, args)
        async with self._connection() as conn:
            rows = await conn.fetch(query, *args)
        return rows if kind is None else [_row_as(kind, row) for row in rows]

    async def fetchrow(self, query: Any, *args: Any) -> Any:
        """The first row or None; with a result type first, checked into it."""
        kind, query, args = _typed(query, args)
        async with self._connection() as conn:
            row = await conn.fetchrow(query, *args)
        return row if kind is None or row is None else _row_as(kind, row)

    async def fetchval(self, query: Any, *args: Any) -> Any:
        """The first column of the first row; with a result type first, checked into it."""
        kind, query, args = _typed(query, args)
        async with self._connection() as conn:
            value = await conn.fetchval(query, *args)
        return value if kind is None else _adapter(kind).validate_python(value)


def _typed(first: Any, args: tuple[Any, ...]) -> tuple[Any, str, tuple[Any, ...]]:
    """`(sql, *args)` or `(result type, sql, *args)`: the type, if any, then the query and its arguments."""
    if isinstance(first, str):
        return None, first, args
    if not args or not isinstance(args[0], str):
        raise TypeError("a typed query is fetch(ResultType, sql, *args)")
    return first, args[0], args[1:]


def _row_as(kind: Any, row: Record) -> Any:
    """A row as `kind`: a model gets the row's columns; any other type gets the row's only column."""
    if isinstance(kind, type) and issubclass(kind, BaseModel):
        return kind.model_validate(dict(row))
    if len(row) != 1:
        raise TypeError(
            f"a row of {len(row)} columns cannot be one {kind!r}; give a model for several columns"
        )
    return _adapter(kind).validate_python(row[0])


def _adapter(kind: Any) -> TypeAdapter[Any]:
    return TypeAdapter(kind)


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
                    yield self._transaction_for(conn)
            finally:
                _open_block.reset(token)
                self._log_if_slow(started)

    def _transaction_for(self, conn: AnyConn) -> Transaction:
        return Transaction(conn)

    def _log_if_slow(self, started: float) -> None:
        held_ms = (self.timing.clock() - started) * 1000
        if self.timing.slow_ms is not None and held_ms > self.timing.slow_ms:
            log.warning("slow transaction", extra={"scope": self.name, "held_ms": held_ms})


class PluginDatabase(Database):
    """Query helpers acting as one plugin: its role and its schema, reset on release (S1)."""

    def __init__(self, pool: Pool, name: str, naming: Naming, timing: Timing | None = None) -> None:
        super().__init__(pool, name, timing)
        self.naming = naming
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


SCHEDULE = "SELECT schedule_job($1, $2, coalesce($3, now()), $4::jsonb, $5, $6)"
UNSCHEDULE = "SELECT unschedule_job($1, $2)"


class ServerScheduling(Queries):
    """Queue one of the plugin's jobs for this server, through the plugin's own `schedule_job` (S1, D31). The
    job records who started it: the member behind the action, or the starter of the job that queued it."""

    guild_id: int
    started_by: int | None = None

    async def schedule(
        self,
        job: Any,
        /,
        *,
        at: datetime | None = None,
        key: str | None = None,
        run_at: datetime | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> int:
        if isinstance(job, Bound):
            handler, data, job_key = job.handler, job.payload, key or job.key
        else:
            handler, data, job_key = str(job), payload or {}, key
        job_id: int = await self.fetchval(
            SCHEDULE, self.guild_id, handler, at or run_at, json.dumps(dict(data)), job_key, self.started_by
        )
        return job_id

    async def unschedule(self, job: Any, /) -> bool:
        job_key = job.key if isinstance(job, Bound) else str(job)
        gone: bool = await self.fetchval(UNSCHEDULE, self.guild_id, job_key)
        return gone


class GuildTransaction(ServerScheduling, Transaction):
    """A plugin's transaction in one server. A job queued here commits with the block's writes."""

    def __init__(self, conn: AnyConn, guild_id: int, started_by: int | None = None) -> None:
        super().__init__(conn)
        self.guild_id = guild_id
        self.started_by = started_by


class GuildPluginDatabase(ServerScheduling, PluginDatabase):
    """What one action or job of a plugin gets as `ctx.db` and `ctx.queue`: bound to one server (D2)."""

    def __init__(self, base: PluginDatabase, guild_id: int, started_by: int | None = None) -> None:
        super().__init__(base.pool, base.name, base.naming, base.timing)
        self.guild_id = guild_id
        self.started_by = started_by

    def _transaction_for(self, conn: AnyConn) -> Transaction:
        return GuildTransaction(conn, self.guild_id, self.started_by)

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[GuildTransaction]:  # pyright: ignore[reportIncompatibleMethodOverride]
        async with super().transaction() as tx:
            assert isinstance(tx, GuildTransaction)
            yield tx


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

    def guild_plugin_db(
        self, plugin_id: str, guild_id: int, started_by: int | None = None
    ) -> GuildPluginDatabase:
        """A plugin's database for one server. Jobs it queues record `started_by` as who started them."""
        return GuildPluginDatabase(self.plugin_db(plugin_id), guild_id, started_by)

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
    plugins = await open_pool(
        Login(info, naming.plugins_role, credentials.plugins_password),
        size,
        connection_class=NoJitConnection,
        server_settings={"jit": "off"},
    )
    return Pools(core, plugins, naming, timing or Timing())


class NoJitConnection(asyncpg.Connection):
    """A plugin connection, which tells asyncpg that the server has no JIT.

    Before looking up a type such as an array, asyncpg calls `set_config('jit', 'off', false)` whenever the server
    supports JIT, even with JIT already off. Plugin roles may not call `set_config` (D9), so that lookup failed.
    The pool turns JIT off when it connects, so reporting no JIT is true, and asyncpg skips the call.
    `_server_caps` is private to asyncpg, which is why teabot pins asyncpg below the next minor release.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._server_caps = self._server_caps._replace(jit=False)  # pyright: ignore[reportUnknownMemberType]


async def open_pool(
    login: Login,
    size: int,
    *,
    connection_class: type[asyncpg.Connection] = asyncpg.Connection,
    server_settings: dict[str, str] | None = None,
) -> Pool:
    """A pool that opens one connection up front and grows to `size`."""
    return await asyncpg.create_pool(
        host=login.info.host,
        port=login.info.port,
        database=login.info.database,
        user=login.user,
        password=login.password,
        min_size=1,
        max_size=size,
        connection_class=connection_class,
        server_settings=server_settings,
    )
