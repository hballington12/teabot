"""pytest fixtures against a real Postgres (D34, D45). Enable with `pytest_plugins = ["teapot.testing.fixtures"]`.

The server's address comes from the TEAPOT_TEST_PG_* variables, defaulting to the instance template's Compose
Postgres. Each test that asks gets a fresh database and a role prefix nobody else uses, because roles live
across the whole server; names carry the test process's pid, and what killed runs left behind is dropped.
"""

import os
import secrets
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import asyncpg
import psycopg
import pytest
from pytest_postgresql import factories

from teapot.db.bootstrap import bootstrap
from teapot.db.naming import Naming
from teapot.db.pool import ConnectionInfo, Credentials, Login, Pools, Timing, create_pools
from teapot.db.types import Conn
from teapot.sdk import Plugin
from teapot.testing.cleanup import cleanup, role_prefix, run_db_name
from teapot.testing.harness import PluginHarness, build_harness

APP_PASSWORD = "app-test"
PLUGINS_PASSWORD = "plugins-test"

postgresql_noproc = factories.postgresql_noproc(  # pyright: ignore[reportUnknownMemberType]
    host=os.environ.get("TEAPOT_TEST_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("TEAPOT_TEST_PG_PORT", "55432")),
    user=os.environ.get("TEAPOT_TEST_PG_USER", "teapot_owner"),
    password=os.environ.get("TEAPOT_TEST_PG_PASSWORD", "teapot"),
    dbname=run_db_name(os.getpid()),
)
postgresql = factories.postgresql("postgresql_noproc")


@pytest.fixture(scope="session", autouse=True)
def _drop_dead_runs(postgresql_noproc: Any) -> None:
    """Drop databases and roles that killed test runs left behind (see `teapot.testing.cleanup`)."""
    with psycopg.connect(
        host=postgresql_noproc.host,
        port=postgresql_noproc.port,
        user=postgresql_noproc.user,
        password=postgresql_noproc.password,
        dbname="postgres",
    ) as conn:
        cleanup(conn)


@pytest.fixture
def info(postgresql: Any) -> ConnectionInfo:
    params = postgresql.info
    return ConnectionInfo(params.host, params.port, params.dbname)


@pytest.fixture
def owner_kwargs(postgresql: Any) -> dict[str, Any]:
    params = postgresql.info
    return {
        "host": params.host,
        "port": params.port,
        "database": params.dbname,
        "user": params.user,
        "password": params.password,
    }


@pytest.fixture
def owner_login(info: ConnectionInfo, owner_kwargs: dict[str, Any]) -> Login:
    return Login(info, owner_kwargs["user"], owner_kwargs["password"])


@pytest.fixture
async def admin(owner_kwargs: dict[str, Any]) -> AsyncIterator[Conn]:
    conn: Conn = await asyncpg.connect(**owner_kwargs)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def naming(admin: Conn) -> AsyncIterator[Naming]:
    """A unique prefix, and every role under it dropped after the test."""
    naming = Naming(role_prefix(os.getpid(), secrets.token_hex(2)))
    yield naming
    roles = await admin.fetch("SELECT rolname FROM pg_roles WHERE rolname LIKE $1", f"{naming.prefix}\\_%")
    for row in roles:
        await admin.execute(f'DROP OWNED BY "{row["rolname"]}" CASCADE')
    for row in roles:
        await admin.execute(f'DROP ROLE "{row["rolname"]}"')


@pytest.fixture
async def pools(admin: Conn, naming: Naming, info: ConnectionInfo) -> AsyncIterator[Pools]:
    await bootstrap(admin, naming, APP_PASSWORD, PLUGINS_PASSWORD)
    pools = await create_pools(
        info, naming, Credentials(APP_PASSWORD, PLUGINS_PASSWORD), size=2, timing=Timing(slow_ms=100)
    )
    try:
        yield pools
    finally:
        await pools.close()


@pytest.fixture
def teapot_harness(admin: Conn, naming: Naming, pools: Pools) -> Callable[[Plugin], Awaitable[PluginHarness]]:
    """`await teapot_harness(plugin)` loads the plugin into a fresh instance and returns its harness."""

    async def make(plugin: Plugin) -> PluginHarness:
        return await build_harness(plugin, admin=admin, naming=naming, pools=pools)

    return make
