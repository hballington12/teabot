"""Database fixtures: a fresh database per test and a role prefix nobody else uses."""

import secrets
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest

from teapot.db.bootstrap import bootstrap
from teapot.db.naming import Naming
from teapot.db.pool import ConnectionInfo, Credentials, Pools, create_pools
from teapot.db.types import Conn

APP_PASSWORD = "app-test"
PLUGINS_PASSWORD = "plugins-test"


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
async def admin(owner_kwargs: dict[str, Any]) -> AsyncIterator[Conn]:
    conn = await asyncpg.connect(**owner_kwargs)
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def naming(admin: Conn) -> AsyncIterator[Naming]:
    """A unique prefix, and every role under it dropped after the test."""
    naming = Naming(f"t{secrets.token_hex(4)}")
    yield naming
    roles = await admin.fetch("SELECT rolname FROM pg_roles WHERE rolname LIKE $1", f"{naming.prefix}\\_%")
    for row in roles:
        await admin.execute(f'DROP OWNED BY "{row["rolname"]}" CASCADE')
    for row in roles:
        await admin.execute(f'DROP ROLE "{row["rolname"]}"')


@pytest.fixture
async def pools(admin: Conn, naming: Naming, info: ConnectionInfo) -> AsyncIterator[Pools]:
    await bootstrap(admin, naming, APP_PASSWORD, PLUGINS_PASSWORD)
    pools = await create_pools(info, naming, Credentials(APP_PASSWORD, PLUGINS_PASSWORD), size=2, slow_ms=100)
    try:
        yield pools
    finally:
        await pools.close()
