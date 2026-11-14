"""pytest fixtures against a real Postgres (D34, D45). Enable with `pytest_plugins = ["teabot.testing.fixtures"]`.

The server's address comes from the TEABOT_TEST_PG_* variables, defaulting to the instance template's Compose
Postgres. The port and password fall back to Compose's TEABOT_DB_PORT and TEABOT_DB_OWNER_PASSWORD, so
`uv run --env-file .env` finds them.

Each test that asks gets a fresh database and a role prefix nobody else uses, because roles live across the
whole server; names carry the test process's pid, and what killed runs left behind is dropped.
"""

import os
import secrets
from collections.abc import AsyncIterator, Iterator
from datetime import timedelta
from typing import Any

import asyncpg
import psycopg
import pytest
from pytest_postgresql import factories

from teabot.db.bootstrap import bootstrap
from teabot.db.naming import Naming
from teabot.db.pool import ConnectionInfo, Credentials, Login, Pools, Timing, create_pools
from teabot.db.types import Conn
from teabot.sdk import LoadablePlugin
from teabot.sdk._clock import CLOCK
from teabot.testing.cleanup import cleanup, role_prefix, run_db_name
from teabot.testing.harness import HarnessFactory, PluginHarness, build_harness

APP_PASSWORD = "app-test"
PLUGINS_PASSWORD = "plugins-test"

PG_HOST = os.environ.get("TEABOT_TEST_PG_HOST", "127.0.0.1")
PG_PORT = int(os.environ.get("TEABOT_TEST_PG_PORT") or os.environ.get("TEABOT_DB_PORT") or "55432")
PG_USER = os.environ.get("TEABOT_TEST_PG_USER", "teabot_owner")
PG_PASSWORD = (
    os.environ.get("TEABOT_TEST_PG_PASSWORD") or os.environ.get("TEABOT_DB_OWNER_PASSWORD") or "teabot"
)
NO_POSTGRES = """teabot's test fixtures could not reach Postgres at {host}:{port} as {user}: {error}
Start the Postgres of your instance's Compose file:
    docker compose up -d --wait postgres
or point the tests at another server with TEABOT_TEST_PG_HOST, TEABOT_TEST_PG_PORT, TEABOT_TEST_PG_USER and
TEABOT_TEST_PG_PASSWORD."""

_teabot_pg_noproc = factories.postgresql_noproc(  # pyright: ignore[reportUnknownMemberType]
    host=PG_HOST, port=PG_PORT, user=PG_USER, password=PG_PASSWORD, dbname=run_db_name(os.getpid())
)


@pytest.fixture(scope="session")
def teabot_pg_server(request: pytest.FixtureRequest) -> Any:
    """The Postgres server the tests use. One quick connection first, so a missing server stops the run at once
    with what to do, instead of pytest-postgresql retrying for a minute."""
    try:
        psycopg.connect(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD,
            dbname="postgres",
            connect_timeout=5,
        ).close()
    except psycopg.OperationalError as exc:
        pytest.exit(NO_POSTGRES.format(host=PG_HOST, port=PG_PORT, user=PG_USER, error=exc), 1)
    return request.getfixturevalue("_teabot_pg_noproc")


teabot_pg = factories.postgresql("teabot_pg_server")


@pytest.fixture(scope="session", autouse=True)
def _drop_dead_runs(teabot_pg_server: Any) -> None:
    """Drop databases and roles that killed test runs left behind (see `teabot.testing.cleanup`)."""
    with psycopg.connect(
        host=teabot_pg_server.host,
        port=teabot_pg_server.port,
        user=teabot_pg_server.user,
        password=teabot_pg_server.password,
        dbname="postgres",
    ) as conn:
        cleanup(conn)


@pytest.fixture
def info(teabot_pg: Any) -> ConnectionInfo:
    params = teabot_pg.info
    return ConnectionInfo(params.host, params.port, params.dbname)


@pytest.fixture
def owner_kwargs(teabot_pg: Any) -> dict[str, Any]:
    params = teabot_pg.info
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
def teabot_harness(admin: Conn, naming: Naming, pools: Pools) -> Iterator[HarnessFactory]:
    """`await teabot_harness(plugin)` loads the plugin into a fresh instance and returns its harness. The test
    clock starts at real time, and goes back to it after the test."""

    async def make(plugin: LoadablePlugin) -> PluginHarness:
        return await build_harness(plugin, admin=admin, naming=naming, pools=pools)

    CLOCK.offset = timedelta()
    yield make
    CLOCK.offset = timedelta()
