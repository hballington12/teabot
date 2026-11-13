"""Plugin purge (D7): the operator's last lifecycle step, which needs no plugin code.

It works with or without the package installed and with the bot running:

1. Take the plugin's advisory lock exclusively. Refuse when that fails, because some process has the plugin
   loaded, and hold it to the end so no process can load the plugin meanwhile.
2. Show what will be deleted and ask.
3. In one transaction: drop the schema as the plugin's role (a schema's owner may drop all it holds), drop
   the role, delete the plugin's rows in `core.guild_plugins`, `core.jobs` and `core.migrations`, queue
   command syncs where it was enabled, and audit the purge for each server and the instance.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from teapot.core.audit import AuditLog
from teapot.core.command_sync import SYNC_HANDLER
from teapot.core.queue import NewJob
from teapot.db.lockkeys import PLUGIN_NS, plugin_key
from teapot.db.naming import Naming
from teapot.db.pool import Transaction
from teapot.db.types import AnyConn
from teapot.sdk.ids import InvalidPluginId, check_plugin_id_free

SERVERS = "SELECT guild_id, enabled FROM core.guild_plugins WHERE plugin_id = $1 ORDER BY guild_id"
JOBS = "SELECT count(*) FROM core.jobs WHERE plugin_id = $1"
MIGRATED = "SELECT count(*) FROM core.migrations WHERE plugin_id = $1"
TABLES = "SELECT tablename FROM pg_tables WHERE schemaname = $1 ORDER BY tablename"
SCHEMA_EXISTS = "SELECT count(*) FROM pg_namespace WHERE nspname = $1"
ROLE_EXISTS = "SELECT count(*) FROM pg_roles WHERE rolname = $1"
CORE_TABLES = ("guild_plugins", "jobs", "migrations")


class PurgeRefused(Exception):
    """Nothing was changed. The message says why."""


@dataclass(frozen=True)
class PurgePlan:
    """What a purge deletes: each table's rows, each server with a row (and whether it is enabled there),
    and the plugin's queued jobs."""

    plugin_id: str
    tables: Mapping[str, int]
    servers: Mapping[int, bool]
    jobs: int

    @property
    def enabled_in(self) -> list[int]:
        return [guild_id for guild_id, enabled in self.servers.items() if enabled]


def quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


async def _table_rows(conn: AnyConn, role: str, schema: str) -> dict[str, int]:
    """Row counts read as the plugin's role, the only role that may read its tables (D9)."""
    tables = [r["tablename"] for r in await conn.fetch(TABLES, schema)]
    if not tables:
        return {}
    await conn.execute(f"SET ROLE {quoted(role)}")
    try:
        return {t: await conn.fetchval(f"SELECT count(*) FROM {quoted(schema)}.{quoted(t)}") for t in tables}
    finally:
        await conn.execute("RESET ROLE")


async def plan_purge(conn: AnyConn, naming: Naming, plugin_id: str) -> PurgePlan:
    role, schema = naming.plugin_role(plugin_id), naming.plugin_schema(plugin_id)
    servers = {r["guild_id"]: r["enabled"] for r in await conn.fetch(SERVERS, plugin_id)}
    jobs: int = await conn.fetchval(JOBS, plugin_id)
    exists = [
        await conn.fetchval(q, a)
        for q, a in ((SCHEMA_EXISTS, schema), (ROLE_EXISTS, role), (MIGRATED, plugin_id))
    ]
    if not (servers or jobs or any(exists)):
        raise PurgeRefused(f"there is nothing called {plugin_id} to purge")
    return PurgePlan(plugin_id, await _table_rows(conn, role, schema), servers, jobs)


async def _drop(conn: AnyConn, naming: Naming, plugin_id: str) -> None:
    role, schema = naming.plugin_role(plugin_id), naming.plugin_schema(plugin_id)
    if await conn.fetchval(SCHEMA_EXISTS, schema):
        await conn.execute(f"SET LOCAL ROLE {quoted(role)}")
        await conn.execute(f"DROP SCHEMA {quoted(schema)} CASCADE")
        await conn.execute("RESET ROLE")
    if await conn.fetchval(ROLE_EXISTS, role):
        await conn.execute(f"DROP ROLE {quoted(role)}")
    for table in CORE_TABLES:
        await conn.execute(f"DELETE FROM core.{table} WHERE plugin_id = $1", plugin_id)


class Purge:
    """Purges plugins over one owner connection, which holds the plugin's exclusive lock throughout."""

    def __init__(self, conn: AnyConn, naming: Naming, audit: AuditLog) -> None:
        self.conn = conn
        self.naming = naming
        self.audit = audit

    async def __call__(
        self, plugin_id: str, *, operator: str, confirm: Callable[[PurgePlan], bool]
    ) -> PurgePlan | None:
        """Purge one plugin everywhere. Returns the plan carried out, or None when `confirm` said no."""
        try:
            check_plugin_id_free(plugin_id)
        except InvalidPluginId as exc:
            raise PurgeRefused(str(exc)) from None
        key = plugin_key(plugin_id)
        if not await self.conn.fetchval("SELECT pg_try_advisory_lock($1, $2)", PLUGIN_NS, key):
            raise PurgeRefused(
                f"a running process has {plugin_id} loaded; block or uninstall it and restart first"
            )
        try:
            plan = await plan_purge(self.conn, self.naming, plugin_id)
            if not confirm(plan):
                return None
            details = {"plugin": plugin_id, "operator": operator}
            async with self.conn.transaction():
                tx = Transaction(self.conn)
                await _drop(self.conn, self.naming, plugin_id)
                for guild_id in plan.enabled_in:
                    await self.audit.queue.schedule(
                        NewJob("core", SYNC_HANDLER, guild_id=guild_id), within=tx
                    )
                for guild_id in [*plan.servers, None]:
                    await self.audit.operator_change(tx, guild_id, "plugins.purge", details)
            return plan
        finally:
            await self.conn.execute("SELECT pg_advisory_unlock($1, $2)", PLUGIN_NS, key)
