"""Plugin purge (WP3.3, D7): the operator's last lifecycle step, needing no plugin code."""

import json
from pathlib import Path
from typing import Any

import asyncpg
import pytest

from teabot.core.audit import AuditLog
from teabot.core.lifecycle import Purge, PurgePlan, PurgeRefused
from teabot.core.queue import Queue
from teabot.db.bootstrap import bootstrap
from teabot.db.lockkeys import PLUGIN_NS, plugin_key
from teabot.db.migrate import PluginMigrations, migrate
from teabot.db.naming import Naming
from teabot.db.pool import ConnectionInfo, Login, Pools, connect
from teabot.db.types import Conn

HERE = 1001
THERE = 1002


@pytest.fixture
async def alpha(admin: Conn, naming: Naming, tmp_path: Path) -> None:
    directory = tmp_path / "alpha"
    directory.mkdir()
    (directory / "0001_t.sql").write_text(
        "CREATE TABLE entries (guild_id bigint, note text); CREATE TABLE prizes (guild_id bigint);"
    )
    await migrate(admin, naming, [PluginMigrations("alpha", directory)])
    await admin.execute(
        "INSERT INTO plugin_alpha.entries VALUES ($1, 'a'), ($1, 'b'), ($2, 'c')", HERE, THERE
    )
    await admin.execute(
        "INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled)"
        " VALUES ($1, 'alpha', true), ($2, 'alpha', false)",
        HERE,
        THERE,
    )
    await admin.execute(
        "INSERT INTO core.jobs (guild_id, plugin_id, handler) VALUES ($1, 'alpha', 'draw')", HERE
    )


@pytest.fixture
def audit(pools: Pools) -> AuditLog:
    return AuditLog(Queue(pools.core_db()))


def yes(seen: list[PurgePlan]) -> Any:
    def confirm(plan: PurgePlan) -> bool:
        seen.append(plan)
        return True

    return confirm


async def test_the_plan_shows_what_will_be_deleted_and_no_changes_nothing(
    admin: Conn, naming: Naming, audit: AuditLog, alpha: None
) -> None:
    seen: list[PurgePlan] = []

    def no(plan: PurgePlan) -> bool:
        seen.append(plan)
        return False

    assert await Purge(admin, naming, audit)("alpha", operator="ops", confirm=no) is None
    assert seen == [PurgePlan("alpha", {"entries": 3, "prizes": 0}, {HERE: True, THERE: False}, jobs=1)]
    assert await admin.fetchval("SELECT count(*) FROM plugin_alpha.entries") == 3


async def test_a_purge_drops_the_schema_role_and_every_core_row(
    admin: Conn, naming: Naming, audit: AuditLog, alpha: None
) -> None:
    await Purge(admin, naming, audit)("alpha", operator="ops", confirm=yes([]))
    assert await admin.fetchval("SELECT count(*) FROM pg_namespace WHERE nspname = 'plugin_alpha'") == 0
    assert (
        await admin.fetchval("SELECT count(*) FROM pg_roles WHERE rolname = $1", naming.plugin_role("alpha"))
        == 0
    )
    for table in ("guild_plugins", "migrations"):
        assert await admin.fetchval(f"SELECT count(*) FROM core.{table} WHERE plugin_id = 'alpha'") == 0
    assert await admin.fetchval("SELECT count(*) FROM core.jobs WHERE plugin_id = 'alpha'") == 0


async def test_servers_that_had_it_enabled_get_a_command_sync(
    admin: Conn, naming: Naming, audit: AuditLog, alpha: None
) -> None:
    await Purge(admin, naming, audit)("alpha", operator="ops", confirm=yes([]))
    rows = await admin.fetch("SELECT guild_id FROM core.jobs WHERE handler = 'sync_commands'")
    assert [r["guild_id"] for r in rows] == [HERE]


async def test_each_server_and_the_instance_get_an_audit_row_naming_the_operator(
    admin: Conn, naming: Naming, audit: AuditLog, alpha: None
) -> None:
    await Purge(admin, naming, audit)("alpha", operator="ops", confirm=yes([]))
    rows = await admin.fetch(
        "SELECT guild_id, user_id, surface, action, input, outcome FROM core.audit_log ORDER BY guild_id"
    )
    assert [(r["guild_id"], r["user_id"], r["surface"], r["action"], r["outcome"]) for r in rows] == [
        (0, 0, "cli", "plugins.purge", "ok"),
        (HERE, 0, "cli", "plugins.purge", "ok"),
        (THERE, 0, "cli", "plugins.purge", "ok"),
    ]
    assert json.loads(rows[0]["input"]) == {"plugin": "alpha", "operator": "ops"}
    posts = await admin.fetch("SELECT guild_id FROM core.jobs WHERE handler = 'post_audit' ORDER BY guild_id")
    assert [r["guild_id"] for r in posts] == [HERE, THERE]


async def test_a_plugin_a_process_has_loaded_is_refused_before_anything_is_shown(
    admin: Conn, naming: Naming, audit: AuditLog, alpha: None, owner_kwargs: dict[str, Any]
) -> None:
    holder = await asyncpg.connect(**owner_kwargs)
    try:
        await holder.execute("SELECT pg_advisory_lock_shared($1, $2)", PLUGIN_NS, plugin_key("alpha"))
        seen: list[PurgePlan] = []
        with pytest.raises(PurgeRefused, match="loaded"):
            await Purge(admin, naming, audit)("alpha", operator="ops", confirm=yes(seen))
        assert seen == []
    finally:
        await holder.close()


async def test_the_lock_is_released_after_a_purge(
    admin: Conn, naming: Naming, audit: AuditLog, alpha: None, owner_kwargs: dict[str, Any]
) -> None:
    await Purge(admin, naming, audit)("alpha", operator="ops", confirm=yes([]))
    other = await asyncpg.connect(**owner_kwargs)
    try:
        assert await other.fetchval("SELECT pg_try_advisory_lock($1, $2)", PLUGIN_NS, plugin_key("alpha"))
    finally:
        await other.close()


@pytest.mark.parametrize(
    ("plugin_id", "message"), [("core", "reserved"), ("nothing", "nothing called nothing")]
)
async def test_reserved_and_unknown_ids_are_refused(
    admin: Conn, naming: Naming, audit: AuditLog, plugin_id: str, message: str
) -> None:
    await migrate(admin, naming, [])
    with pytest.raises(PurgeRefused, match=message):
        await Purge(admin, naming, audit)(plugin_id, operator="ops", confirm=yes([]))


async def test_rows_left_by_a_plugin_with_no_schema_are_purged(
    admin: Conn, naming: Naming, audit: AuditLog
) -> None:
    await migrate(admin, naming, [])
    await admin.execute(
        "INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled) VALUES ($1, 'gone', true)", HERE
    )
    seen: list[PurgePlan] = []
    await Purge(admin, naming, audit)("gone", operator="ops", confirm=yes(seen))
    assert seen == [PurgePlan("gone", {}, {HERE: True}, jobs=0)]
    assert await admin.fetchval("SELECT count(*) FROM core.guild_plugins") == 0


async def test_an_owner_that_is_not_a_superuser_can_purge(
    admin: Conn, naming: Naming, owner_kwargs: dict[str, Any], info: ConnectionInfo, tmp_path: Path
) -> None:
    owner = f"{naming.prefix}_owner"
    database = owner_kwargs["database"]
    await admin.execute(f"CREATE ROLE \"{owner}\" LOGIN CREATEROLE PASSWORD 'o'")
    await admin.execute(f'ALTER DATABASE "{database}" OWNER TO "{owner}"')
    await admin.execute(f'GRANT CREATE ON DATABASE "{database}" TO "{owner}"')
    directory = tmp_path / "alpha"
    directory.mkdir()
    (directory / "0001_t.sql").write_text("CREATE TABLE entries (guild_id bigint);")
    try:
        conn = await connect(Login(info, owner, "o"))
        try:
            await bootstrap(conn, naming, "a", "p")
            assert not (await migrate(conn, naming, [PluginMigrations("alpha", directory)])).failed
            pools_audit = AuditLog(Queue(_Single(conn)))  # type: ignore[arg-type]
            await Purge(conn, naming, pools_audit)("alpha", operator="ops", confirm=yes([]))
            assert (
                await conn.fetchval("SELECT count(*) FROM pg_namespace WHERE nspname = 'plugin_alpha'") == 0
            )
        finally:
            await conn.close()
    finally:
        await admin.execute(f'ALTER DATABASE "{database}" OWNER TO "{owner_kwargs["user"]}"')


class _Single:
    """A `Database` over one connection, for the non-superuser test."""

    def __init__(self, conn: Conn) -> None:
        self.conn = conn

    async def fetchval(self, query: str, *args: Any) -> Any:
        return await self.conn.fetchval(query, *args)

    async def execute(self, query: str, *args: Any) -> Any:
        return await self.conn.execute(query, *args)
