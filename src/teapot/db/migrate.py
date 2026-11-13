"""The migration runner (D9, D15).

Runs on one owner connection, under an advisory lock so processes starting together migrate once.
The core migrates first. Then each plugin gets its role, schema and `schedule_job` function, and its
files run one transaction each, as the plugin's role. A plugin whose migration fails is reported and
skipped; the others carry on. A failure in the core's own migrations is fatal.
"""

import hashlib
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path

import asyncpg

from teapot.db.lockkeys import MIGRATION_NS
from teapot.db.naming import Naming
from teapot.db.types import Conn

log = logging.getLogger(__name__)

CORE = "core"
FILE_RE = re.compile(r"(\d{4})_([a-z0-9_]+)\.sql")
CORE_MIGRATIONS = Path(str(files("teapot.db") / "migrations"))

RUNNER_SETUP = """
CREATE SCHEMA IF NOT EXISTS core;
CREATE TABLE IF NOT EXISTS core.migrations (
    plugin_id text NOT NULL,
    version integer NOT NULL,
    name text NOT NULL,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (plugin_id, version)
);
"""

MISSING_GUILD_ID = """
SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = $1 AND c.relkind IN ('r', 'p') AND NOT EXISTS (
    SELECT 1 FROM pg_attribute a
    WHERE a.attrelid = c.oid AND a.attname = 'guild_id' AND a.atttypid = 'bigint'::regtype AND NOT a.attisdropped
)
"""


class MigrationError(Exception):
    """A plugin's migrations cannot be applied as they stand."""


@dataclass(frozen=True)
class MigrationFile:
    version: int
    name: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text()

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class PluginMigrations:
    plugin_id: str
    directory: Path | None


@dataclass
class MigrationReport:
    applied: dict[str, list[int]] = field(default_factory=dict[str, list[int]])
    failed: dict[str, str] = field(default_factory=dict[str, str])


def read_files(directory: Path | None) -> list[MigrationFile]:
    """The files in order, refusing bad names, duplicates and gaps."""
    if directory is None or not directory.exists():
        return []
    found: list[MigrationFile] = []
    for path in sorted(directory.glob("*.sql")):
        match = FILE_RE.fullmatch(path.name)
        if not match:
            raise MigrationError(f"{path.name}: migration files are named NNNN_name.sql")
        found.append(MigrationFile(int(match.group(1)), match.group(2), path))
    versions = [f.version for f in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError(
            f"migrations in {directory} must be numbered 1, 2, 3 and so on, found {versions}"
        )
    return found


async def _applied(conn: Conn, plugin_id: str) -> dict[int, str]:
    rows = await conn.fetch("SELECT version, checksum FROM core.migrations WHERE plugin_id = $1", plugin_id)
    return {r["version"]: r["checksum"] for r in rows}


def _pending(plugin_id: str, found: list[MigrationFile], applied: dict[int, str]) -> list[MigrationFile]:
    if applied and max(applied) > len(found):
        raise MigrationError(
            f"{plugin_id}: database is at version {max(applied)}, files stop at {len(found)}"
        )
    for f in found:
        if f.version in applied and applied[f.version] != f.checksum:
            raise MigrationError(f"{plugin_id}: {f.path.name} changed after it was applied")
    return [f for f in found if f.version not in applied]


async def _setup_core(conn: Conn, naming: Naming) -> None:
    owner = await conn.fetchval("SELECT current_user")
    app = naming.app_role
    await conn.execute(RUNNER_SETUP)
    await conn.execute(f'GRANT USAGE ON SCHEMA core TO "{app}"')
    await conn.execute(
        f'ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA core '
        f'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{app}"'
    )
    await conn.execute(
        f'ALTER DEFAULT PRIVILEGES FOR ROLE "{owner}" IN SCHEMA core GRANT USAGE, SELECT ON SEQUENCES TO "{app}"'
    )
    await conn.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core TO "{app}"')
    await conn.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA core TO "{app}"')


async def _setup_plugin(conn: Conn, naming: Naming, plugin_id: str) -> None:
    role, schema = naming.plugin_role(plugin_id), naming.plugin_schema(plugin_id)
    if not await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role):
        await conn.execute(f'CREATE ROLE "{role}" NOLOGIN')
    await conn.execute(f'GRANT "{role}" TO "{naming.plugins_role}" WITH INHERIT FALSE, SET TRUE')
    await conn.execute(f'GRANT "{role}" TO CURRENT_USER WITH INHERIT FALSE, SET TRUE')
    await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}" AUTHORIZATION "{role}"')
    await conn.execute(SCHEDULE_JOB.format(schema=schema, plugin_id=plugin_id))
    await conn.execute(
        f'REVOKE ALL ON FUNCTION "{schema}".schedule_job(bigint, text, timestamptz, jsonb) FROM PUBLIC'
    )
    await conn.execute(
        f'GRANT EXECUTE ON FUNCTION "{schema}".schedule_job(bigint, text, timestamptz, jsonb) TO "{role}"'
    )


SCHEDULE_JOB = """
CREATE OR REPLACE FUNCTION "{schema}".schedule_job(
    p_guild_id bigint, p_handler text, p_run_at timestamptz DEFAULT now(), p_payload jsonb DEFAULT '{{}}'
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_temp AS $$
DECLARE new_id bigint;
BEGIN
    INSERT INTO core.jobs (guild_id, plugin_id, handler, run_at, payload)
    VALUES (p_guild_id, '{plugin_id}', p_handler, p_run_at, p_payload) RETURNING id INTO new_id;
    IF p_run_at <= now() THEN PERFORM pg_notify('teapot_jobs', new_id::text); END IF;
    RETURN new_id;
END $$
"""


async def _apply(conn: Conn, naming: Naming, plugin_id: str, migration: MigrationFile) -> None:
    async with conn.transaction():
        if plugin_id == CORE:
            await conn.execute("SET LOCAL search_path TO core")
        else:
            schema = naming.plugin_schema(plugin_id)
            await conn.execute(f'SET LOCAL ROLE "{naming.plugin_role(plugin_id)}"')
            await conn.execute(f'SET LOCAL search_path TO "{schema}"')
        await conn.execute(migration.sql)
        await conn.execute("RESET ROLE")
        if plugin_id != CORE:
            missing = [
                r["relname"] for r in await conn.fetch(MISSING_GUILD_ID, naming.plugin_schema(plugin_id))
            ]
            if missing:
                raise MigrationError(
                    f"{plugin_id}: tables without a bigint guild_id column: {', '.join(missing)}"
                )
        await conn.execute(
            "INSERT INTO core.migrations (plugin_id, version, name, checksum) VALUES ($1, $2, $3, $4)",
            plugin_id,
            migration.version,
            migration.name,
            migration.checksum,
        )


async def _migrate_one(conn: Conn, naming: Naming, plugin_id: str, directory: Path | None) -> list[int]:
    pending = _pending(plugin_id, read_files(directory), await _applied(conn, plugin_id))
    for migration in pending:
        await _apply(conn, naming, plugin_id, migration)
        log.info("applied migration", extra={"plugin": plugin_id, "file": migration.path.name})
    return [m.version for m in pending]


async def migrate(conn: Conn, naming: Naming, plugins: Sequence[PluginMigrations]) -> MigrationReport:
    """Migrate the core, then every plugin. Holds the migration lock for the whole run."""
    report = MigrationReport()
    await conn.execute("SELECT pg_advisory_lock($1, 0)", MIGRATION_NS)
    try:
        await _setup_core(conn, naming)
        report.applied[CORE] = await _migrate_one(conn, naming, CORE, CORE_MIGRATIONS)
        for plugin in plugins:
            try:
                await _setup_plugin(conn, naming, plugin.plugin_id)
                report.applied[plugin.plugin_id] = await _migrate_one(
                    conn, naming, plugin.plugin_id, plugin.directory
                )
            except (MigrationError, asyncpg.PostgresError) as exc:
                report.failed[plugin.plugin_id] = str(exc)
                log.error("plugin migration failed", extra={"plugin": plugin.plugin_id, "error": str(exc)})
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1, 0)", MIGRATION_NS)
    return report
