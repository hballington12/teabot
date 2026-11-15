"""Plugin purge (D7) and guild removal (D49): the lifecycle steps that delete data, needing no plugin code.

Plugin purge works with or without the package installed and with the bot running:

1. Take the plugin's advisory lock exclusively. Refuse when that fails, because some process has the plugin
   loaded, and hold it to the end so no process can load the plugin meanwhile.
2. Show what will be deleted and ask.
3. In one transaction: drop the schema as the plugin's role (a schema's owner may drop all it holds), drop
   the role, delete the plugin's rows in `core.guild_plugins`, `core.jobs` and `core.migrations`, queue
   command syncs where it was enabled, and audit the purge for each server and the instance.

Guild removal keeps a server's data for a grace period. Its jobs pause, and a `purge_guild` job is queued
for the end of the period. A return within it cancels the purge, and everything is as it was. The purge
deletes the server's rows from every plugin schema, each as its plugin's role, then from every core table.
Servers that joined or left while the bot was down are found at startup.
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from teabot.core.audit import AuditLog
from teabot.core.command_sync import SYNC_HANDLER, CommandSync
from teabot.core.queue import JobContext, NewJob, Queue, ShardFilter
from teabot.db.lockkeys import PLUGIN_NS, plugin_key
from teabot.db.naming import Naming
from teabot.db.pool import Pools, Transaction
from teabot.db.types import AnyConn
from teabot.sdk.ids import InvalidPluginId, check_plugin_id_free

SERVERS = "SELECT guild_id, enabled FROM core.guild_plugins WHERE plugin_id = $1 ORDER BY guild_id"
JOBS = "SELECT count(*) FROM core.jobs WHERE plugin_id = $1"
MIGRATED = "SELECT count(*) FROM core.migrations WHERE plugin_id = $1"
TABLES = "SELECT tablename FROM pg_tables WHERE schemaname = $1 ORDER BY tablename"
SCHEMA_EXISTS = "SELECT count(*) FROM pg_namespace WHERE nspname = $1"
ROLE_EXISTS = "SELECT count(*) FROM pg_roles WHERE rolname = $1"
CORE_TABLES = ("guild_plugins", "jobs", "migrations", "posts")


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
    for name in (role, naming.plugin_runtime_role(plugin_id)):
        if await conn.fetchval(ROLE_EXISTS, name):
            await conn.execute(f"DROP ROLE {quoted(name)}")
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


PURGE_GUILD = "purge_guild"
ACTIVE = "SELECT guild_id FROM core.guilds WHERE removed_at IS NULL"
JOIN = """
INSERT INTO core.guilds (guild_id) VALUES ($1)
ON CONFLICT (guild_id) DO UPDATE SET removed_at = NULL, purge_job_id = NULL, joined_at = now()
WHERE core.guilds.removed_at IS NOT NULL
RETURNING (SELECT purge_job_id FROM core.guilds WHERE guild_id = $1) AS cancelled_job
"""
CANCEL = "UPDATE core.jobs SET state = 'cancelled', finished_at = now() WHERE id = $1 AND state = 'pending'"
REMOVE = """
INSERT INTO core.guilds (guild_id, removed_at) VALUES ($1, now())
ON CONFLICT (guild_id) DO UPDATE SET removed_at = now() WHERE core.guilds.removed_at IS NULL
RETURNING guild_id
"""
SET_PURGE_JOB = "UPDATE core.guilds SET purge_job_id = $2 WHERE guild_id = $1"
FORGET_COMMANDS = "DELETE FROM core.command_sync WHERE guild_id = $1"
STILL_REMOVED = "SELECT removed_at IS NOT NULL FROM core.guilds WHERE guild_id = $1"
PLUGIN_SCHEMAS = "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'plugin\\_%' ORDER BY nspname"
# Ordinary and partitioned tables with a guild_id column; a partition is reached through its parent.
GUILD_TABLES = """
SELECT c.relname FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'guild_id' AND NOT a.attisdropped
WHERE n.nspname = $1 AND c.relkind IN ('r', 'p') AND NOT c.relispartition
ORDER BY c.relname
"""


class Guilds:
    """The servers the bot is in, from the gateway's join and remove events and a comparison at startup."""

    def __init__(self, pools: Pools, queue: Queue, sync: CommandSync, retention: timedelta) -> None:
        self.pools = pools
        self.db = pools.core_db()
        self.queue = queue
        self.sync = sync
        self.retention = retention

    async def joined(self, guild_id: int) -> None:
        """Record a new server, or bring back a removed one: its purge is cancelled and its jobs resume."""
        async with self.db.transaction() as tx:
            cancelled = await tx.fetchval(JOIN, guild_id)
            if cancelled is not None:
                await tx.execute(CANCEL, cancelled)
        await self.sync.request(guild_id)

    async def removed(self, guild_id: int) -> None:
        """Start the grace period. A repeated event changes nothing."""
        async with self.db.transaction() as tx:
            if await tx.fetchval(REMOVE, guild_id) is None:
                return
            job = NewJob("core", PURGE_GUILD, guild_id=guild_id, run_at=datetime.now(UTC) + self.retention)
            await tx.execute(SET_PURGE_JOB, guild_id, await self.queue.schedule(job, within=tx))
            # Discord drops a server's commands when the bot leaves, so a return must send them again.
            await tx.execute(FORGET_COMMANDS, guild_id)

    async def reconcile(self, present: Iterable[int], shards: ShardFilter | None) -> tuple[int, int]:
        """Compare the servers the gateway reports with `core.guilds`, on this process's shards only.
        Returns how many joined and how many left while the bot was down."""
        here = set(present)
        active = {r["guild_id"] for r in await self.db.fetch(ACTIVE)}
        if shards is not None:
            active = {g for g in active if (g >> 22) % shards.shard_count in shards.shard_ids}
        for guild_id in sorted(here - active):
            await self.joined(guild_id)
        for guild_id in sorted(active - here):
            await self.removed(guild_id)
        return len(here - active), len(active - here)

    async def purge(self, ctx: JobContext) -> None:
        """The `purge_guild` handler: one transaction per plugin schema, then one for the core, which deletes
        this job's own row with the rest. Every step is safe to repeat, so a failed run simply retries."""
        guild_id = ctx.job.guild_id
        if guild_id is None or not await self.db.fetchval(STILL_REMOVED, guild_id):
            return
        for row in await self.db.fetch(PLUGIN_SCHEMAS):
            plugin = self.pools.guild_plugin_db(row["nspname"].removeprefix("plugin_"), guild_id)
            async with plugin.transaction() as tx:
                for table in await tx.fetch(GUILD_TABLES, row["nspname"]):
                    await tx.execute(f"DELETE FROM {quoted(table['relname'])} WHERE guild_id = $1", guild_id)
        async with self.db.transaction() as tx:
            for table in await tx.fetch(GUILD_TABLES, "core"):
                await tx.execute(f"DELETE FROM core.{quoted(table['relname'])} WHERE guild_id = $1", guild_id)
