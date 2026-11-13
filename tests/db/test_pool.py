"""The pools, role switching and the escapes spike S1 found (WP1.3)."""

import asyncio
import logging

import asyncpg
import pytest

from teapot.db.naming import Naming
from teapot.db.pool import BlockOpenError, Database, Pools, Timing
from teapot.db.types import Conn


async def make_plugin(admin: Conn, naming: Naming, plugin_id: str, rows: list[str]) -> None:
    """Stand-in for the migration runner: role, schema and a table with rows."""
    role, schema = naming.plugin_role(plugin_id), naming.plugin_schema(plugin_id)
    await admin.execute(f'CREATE ROLE "{role}" NOLOGIN')
    await admin.execute(f'GRANT "{role}" TO "{naming.plugins_role}"')
    await admin.execute(f'CREATE SCHEMA "{schema}" AUTHORIZATION "{role}"')
    await admin.execute(f'SET ROLE "{role}"')
    await admin.execute(f'CREATE TABLE "{schema}".entries (guild_id bigint, name text)')
    for name in rows:
        await admin.execute(f'INSERT INTO "{schema}".entries VALUES (1, $1)', name)
    await admin.execute("RESET ROLE")


async def make_core_secret(admin: Conn, naming: Naming) -> None:
    await admin.execute("CREATE SCHEMA core")
    await admin.execute("CREATE TABLE core.tokens (guild_id bigint, secret_hash text)")
    await admin.execute("INSERT INTO core.tokens VALUES (1, 'SECRET')")
    await admin.execute(f'GRANT USAGE ON SCHEMA core TO "{naming.app_role}"')
    await admin.execute(f'GRANT SELECT ON core.tokens TO "{naming.app_role}"')


@pytest.fixture
async def world(admin: Conn, naming: Naming, pools: Pools) -> Pools:
    await make_core_secret(admin, naming)
    await make_plugin(admin, naming, "alpha", ["alice"])
    await make_plugin(admin, naming, "beta", ["beta-private"])
    return pools


async def test_plugin_reads_its_own_schema_unqualified(world: Pools) -> None:
    rows = await world.plugin_db("alpha").fetch("SELECT name FROM entries")
    assert [r["name"] for r in rows] == ["alice"]


async def test_core_reads_core(world: Pools) -> None:
    assert await world.core_db().fetchval("SELECT secret_hash FROM core.tokens") == "SECRET"


async def test_role_is_reset_on_release(world: Pools, naming: Naming) -> None:
    await world.plugin_db("alpha").fetch("SELECT 1")
    async with world.plugins.acquire() as conn:
        assert await conn.fetchval("SELECT current_user") == naming.plugins_role
        assert await conn.fetchval("SHOW search_path") == '"$user", public'


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM core.tokens",
        "SELECT * FROM plugin_beta.entries",
        "SELECT name FROM entries WHERE name = 'x' UNION SELECT secret_hash FROM core.tokens",
    ],
)
async def test_plugin_cannot_reach_outside(world: Pools, query: str) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await world.plugin_db("alpha").fetch(query)


async def test_stacked_statements_are_refused_by_every_helper(world: Pools) -> None:
    db = world.plugin_db("alpha")
    stacked = "SELECT 1; RESET ROLE"
    for call in (db.execute, db.fetch, db.fetchrow, db.fetchval):
        with pytest.raises(asyncpg.PostgresSyntaxError):
            await call(stacked)


async def test_injected_set_config_is_refused(world: Pools) -> None:
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="set_config"):
        await world.plugin_db("alpha").fetch("SELECT set_config('role', 'none', false)")


async def test_plpgsql_cannot_set_role_to_app(world: Pools, naming: Naming) -> None:
    db = world.plugin_db("alpha")
    await db.execute(
        "CREATE FUNCTION run_dynamic(sql text) RETURNS void LANGUAGE plpgsql AS $$ BEGIN EXECUTE sql; END $$"
    )
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="set role"):
        await db.fetch(f"SELECT run_dynamic('SET ROLE \"{naming.app_role}\"')")


async def test_execute_returns_status(world: Pools) -> None:
    assert await world.plugin_db("alpha").execute("INSERT INTO entries VALUES (1, 'bob')") == "INSERT 0 1"


async def test_transaction_commits_and_sees_own_writes(world: Pools) -> None:
    db = world.plugin_db("alpha")
    async with db.transaction() as tx:
        await tx.execute("INSERT INTO entries VALUES ($1, $2)", 1, "carol")
        assert await tx.fetchval("SELECT count(*) FROM entries") == 2
    assert await db.fetchval("SELECT count(*) FROM entries") == 2


async def test_transaction_rolls_back_on_error(world: Pools) -> None:
    db = world.plugin_db("alpha")
    with pytest.raises(ValueError):
        async with db.transaction() as tx:
            await tx.execute("INSERT INTO entries VALUES ($1, $2)", 1, "dave")
            raise ValueError
    assert await db.fetchval("SELECT count(*) FROM entries") == 1


async def test_db_inside_open_block_raises(world: Pools) -> None:
    db = world.plugin_db("alpha")
    async with db.transaction():
        with pytest.raises(BlockOpenError):
            await db.fetch("SELECT 1")
        await world.plugin_db("beta").fetch("SELECT 1")


async def test_two_transactions_run_concurrently(world: Pools) -> None:
    db = world.plugin_db("alpha")

    async def insert(name: str) -> None:
        async with db.transaction() as tx:
            await tx.execute("INSERT INTO entries VALUES ($1, $2)", 1, name)
            await asyncio.sleep(0.05)

    await asyncio.gather(insert("e1"), insert("e2"))
    assert await db.fetchval("SELECT count(*) FROM entries") == 3


async def test_slow_transaction_is_logged(world: Pools, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="teapot.db.pool")
    async with world.plugin_db("alpha").transaction():
        await asyncio.sleep(0.15)
    assert any(r.message == "slow transaction" for r in caplog.records)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1024.0  # exact in binary, like every step below

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize(
    ("slow_ms", "held_s", "logged"),
    [(125, 0.25, True), (125, 0.125, False), (125, 0.0625, False), (None, 8.0, False)],
)
async def test_slow_transactions_are_logged_past_the_threshold(
    world: Pools, caplog: pytest.LogCaptureFixture, slow_ms: float | None, held_s: float, logged: bool
) -> None:
    clock = FakeClock()
    db = Database(world.core, "core", Timing(slow_ms=slow_ms, clock=clock))
    caplog.set_level(logging.WARNING, logger="teapot.db.pool")
    async with db.transaction():
        clock.now += held_s
    records = [r for r in caplog.records if r.message == "slow transaction"]
    assert bool(records) is logged
    if logged:
        assert records[0].__dict__["held_ms"] == pytest.approx(held_s * 1000)


async def test_core_db_inside_its_own_open_block_raises(world: Pools) -> None:
    db = world.core_db()
    async with db.transaction():
        with pytest.raises(BlockOpenError):
            await db.fetch("SELECT 1")


async def test_pools_open_one_connection_each_up_front(world: Pools) -> None:
    assert world.core.get_size() == 1
    assert world.plugins.get_size() == 1
