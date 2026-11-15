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

from teabot.db.lockkeys import MIGRATION_NS
from teabot.db.naming import Naming
from teabot.db.types import AnyConn, Conn

log = logging.getLogger(__name__)

CORE = "core"
FILE_RE = re.compile(r"(\d{4})_([a-z0-9_]+)\.sql")
CORE_MIGRATIONS = Path(str(files("teabot.db") / "migrations"))

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
-- A member's Discord ID, as a type: deleting a member's data finds every column of it (D11).
CREATE SCHEMA IF NOT EXISTS teabot;
GRANT USAGE ON SCHEMA teabot TO PUBLIC;
DO $$ BEGIN
    IF to_regtype('teabot.member_id') IS NULL THEN
        CREATE DOMAIN teabot.member_id AS bigint;
    END IF;
END $$;
"""

MISSING_GUILD_ID = """
SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = $1 AND c.relkind IN ('r', 'p') AND NOT EXISTS (
    SELECT 1 FROM pg_attribute a
    WHERE a.attrelid = c.oid AND a.attname = 'guild_id' AND a.atttypid = 'bigint'::regtype AND NOT a.attisdropped
)
"""


# Foreign keys that leave out guild_id: a member could point a row at another server's, revealing that it exists,
# and that row would block the other server's data removal (D49, S6).
LOOSE_FOREIGN_KEYS = """
SELECT c.conname, t.relname FROM pg_constraint c JOIN pg_class t ON t.oid = c.conrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = $1 AND c.contype = 'f' AND NOT EXISTS (
    SELECT 1 FROM unnest(c.conkey) k JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k
    WHERE a.attname = 'guild_id')
ORDER BY t.relname, c.conname
"""

# Unique indexes that leave out guild_id collide across servers, unless they hold an identity column, which is
# unique on its own (S6).
LOOSE_UNIQUE = """
SELECT i.indexrelid::regclass::text AS index_name, t.relname FROM pg_index i JOIN pg_class t ON t.oid = i.indrelid
JOIN pg_namespace n ON n.oid = t.relnamespace
WHERE n.nspname = $1 AND i.indisunique AND NOT EXISTS (
    SELECT 1 FROM pg_attribute a WHERE a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
    AND (a.attname = 'guild_id' OR a.attidentity IN ('a', 'd')))
ORDER BY 1
"""

# Objects that read tables with someone else's rights, or keep a copy outside them (S6). The instance owner's own
# functions, such as schedule_job, are SECURITY DEFINER by design.
BYPASSES = """
SELECT c.relname AS name, c.relkind::text AS kind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = $1 AND (c.relkind = 'm' OR (c.relkind = 'v'
    AND NOT coalesce('security_invoker=true' = ANY(c.reloptions) OR 'security_invoker=on' = ANY(c.reloptions), false)))
UNION ALL
SELECT p.proname, 'f' FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = $1 AND p.prosecdef AND p.proowner <> (SELECT oid FROM pg_roles WHERE rolname = current_user)
ORDER BY 1
"""

BYPASS_FIX = {
    "v": "view {name} runs with its owner's rights and sees every server's rows; "
    "create it WITH (security_invoker = true)",
    "m": "materialized view {name} keeps every server's rows outside the plugin's tables; use a table with guild_id",
    "f": "function {name} is SECURITY DEFINER, so it sees every server's rows; drop SECURITY DEFINER",
}


# bigint columns named for a member, such as member_id, winner_ids or user_id, that deleting a member's data would
# miss (D11).
UNTYPED_MEMBERS = """
SELECT c.relname, a.attname, a.atttypid = 'bigint[]'::regtype AS is_array FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = $1 AND c.relkind IN ('r', 'p') AND NOT c.relispartition AND a.attnum > 0 AND NOT a.attisdropped
AND a.atttypid IN ('bigint'::regtype, 'bigint[]'::regtype) AND a.attname ~ '(^|_)(member|user|winner)s?(_ids?)?$'
AND a.attname NOT IN ('members', 'users', 'winners')
ORDER BY 1, 2
"""


async def schema_problems(conn: Conn, schema: str, *, members: bool = True) -> list[str]:
    """What in a plugin's schema could mix servers' data, each with what to write instead."""
    found = [
        f"foreign key {r['conname']} on {r['relname']} leaves out guild_id; write FOREIGN KEY (guild_id, ...) "
        f"REFERENCES ... (guild_id, ...), against a UNIQUE (guild_id, ...) on the parent"
        for r in await conn.fetch(LOOSE_FOREIGN_KEYS, schema)
    ]
    found += [
        f"unique index {r['index_name'].split('.')[-1].strip(chr(34))} on {r['relname']} leaves out guild_id, so it "
        f"collides across servers; make it UNIQUE (guild_id, ...)"
        for r in await conn.fetch(LOOSE_UNIQUE, schema)
    ]
    found += [BYPASS_FIX[r["kind"]].format(name=r["name"]) for r in await conn.fetch(BYPASSES, schema)]
    found += [
        f"column {r['relname']}.{r['attname']} holds members' IDs as bigint{'[]' if r['is_array'] else ''}, "
        f"which deleting a member's data would miss; give it the type "
        f"teabot.member_id{'[]' if r['is_array'] else ''}"
        for r in (await conn.fetch(UNTYPED_MEMBERS, schema) if members else [])
    ]
    return found


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
    runtime = naming.plugin_runtime_role(plugin_id)
    for name in (role, runtime):
        if not await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", name):
            await conn.execute(f'CREATE ROLE "{name}" NOLOGIN')
        await conn.execute(f'GRANT "{name}" TO CURRENT_USER WITH INHERIT FALSE, SET TRUE')
    # Plugin code runs as the runtime role, which the policies hold to one server; the owner role is for
    # migrations alone, so the plugin pool may no longer become it (S6).
    await conn.execute(f'GRANT "{runtime}" TO "{naming.plugins_role}" WITH INHERIT FALSE, SET TRUE')
    await conn.execute(f'REVOKE "{role}" FROM "{naming.plugins_role}"')
    await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}" AUTHORIZATION "{role}"')
    # The owner holds the plugin role without inheriting it, so it has no rights in the plugin's schema. The
    # role, as the schema's owner, grants it CREATE, so the owner can create schedule_job there. The function
    # stays the owner's, so the plugin cannot rewrite what it runs as SECURITY DEFINER (D9, D30).
    owner = await conn.fetchval("SELECT current_user")
    await conn.execute(f'SET ROLE "{role}"')
    try:
        await conn.execute(f'GRANT USAGE, CREATE ON SCHEMA "{schema}" TO "{owner}"')
        await conn.execute(RUNTIME_GRANTS.format(schema=schema, runtime=runtime))
    finally:
        await conn.execute("RESET ROLE")
    # Earlier releases had a four-argument schedule_job; a new signature is a new function, so the old one goes.
    await conn.execute(f'DROP FUNCTION IF EXISTS "{schema}".schedule_job(bigint, text, timestamptz, jsonb)')
    functions = (
        (SCHEDULE_JOB, SCHEDULE_SIGNATURE),
        (UNSCHEDULE_JOB, UNSCHEDULE_SIGNATURE),
        (QUEUE_POST, QUEUE_POST_SIGNATURE),
    )
    for definition, signature in functions:
        await conn.execute(definition.format(schema=schema, plugin_id=plugin_id))
        await conn.execute(f'REVOKE ALL ON FUNCTION "{schema}".{signature} FROM PUBLIC')
        await conn.execute(f'GRANT EXECUTE ON FUNCTION "{schema}".{signature} TO "{runtime}"')


QUEUE_POST_SIGNATURE = "queue_post(bigint, bigint, bigint, jsonb, boolean, bigint)"
SCHEDULE_SIGNATURE = "schedule_job(bigint, text, timestamptz, jsonb, text, bigint)"
UNSCHEDULE_SIGNATURE = "unschedule_job(bigint, text)"

# A key makes scheduling idempotent: the same key moves the pending job, and the partial unique index of
# core.jobs makes a running job with that key no obstacle to a new pending one.
SCHEDULE_JOB = """
CREATE OR REPLACE FUNCTION "{schema}".schedule_job(
    p_guild_id bigint, p_handler text, p_run_at timestamptz DEFAULT now(), p_payload jsonb DEFAULT '{{}}',
    p_key text DEFAULT NULL, p_started_by bigint DEFAULT NULL
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_temp AS $$
DECLARE new_id bigint;
BEGIN
    INSERT INTO core.jobs (guild_id, plugin_id, handler, run_at, payload, key, started_by)
    VALUES (p_guild_id, '{plugin_id}', p_handler, p_run_at, p_payload, p_key, p_started_by)
    ON CONFLICT (plugin_id, guild_id, key) WHERE state = 'pending' AND key IS NOT NULL
    DO UPDATE SET run_at = EXCLUDED.run_at, payload = EXCLUDED.payload, handler = EXCLUDED.handler,
                  started_by = EXCLUDED.started_by
    RETURNING id INTO new_id;
    PERFORM pg_notify('teabot_jobs', new_id::text);
    RETURN new_id;
END $$
"""

UNSCHEDULE_JOB = """
CREATE OR REPLACE FUNCTION "{schema}".unschedule_job(p_guild_id bigint, p_key text)
RETURNS boolean LANGUAGE sql SECURITY DEFINER SET search_path = core, pg_temp AS $$
    WITH gone AS (
        DELETE FROM core.jobs
        WHERE plugin_id = '{plugin_id}' AND guild_id = p_guild_id AND key = p_key AND state = 'pending'
        RETURNING 1
    )
    SELECT EXISTS (SELECT 1 FROM gone)
$$
"""


# The outbox (tx.send): a new post, or a change to one of this plugin's posts in this server, and a core job to
# bring Discord up to date. p_post_id is NULL for a new post; p_message NULL leaves what it shows alone.
QUEUE_POST = """
CREATE OR REPLACE FUNCTION "{schema}".queue_post(
    p_guild_id bigint, p_post_id bigint, p_channel_id bigint, p_message jsonb, p_deleted boolean DEFAULT false,
    p_started_by bigint DEFAULT NULL
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER SET search_path = core, pg_temp AS $$
DECLARE post_id bigint; job_id bigint;
BEGIN
    IF p_post_id IS NULL THEN
        INSERT INTO core.posts (guild_id, plugin_id, channel_id, message)
        VALUES (p_guild_id, '{plugin_id}', p_channel_id, p_message)
        RETURNING id INTO post_id;
    ELSE
        UPDATE core.posts
        SET message = coalesce(p_message, message), deleted = deleted OR p_deleted, version = version + 1
        WHERE id = p_post_id AND guild_id = p_guild_id AND plugin_id = '{plugin_id}'
        RETURNING id INTO post_id;
        IF post_id IS NULL THEN
            RAISE EXCEPTION 'post % is not one of this plugin''s posts in this server', p_post_id
                USING ERRCODE = 'no_data_found';
        END IF;
    END IF;
    INSERT INTO core.jobs (guild_id, plugin_id, handler, payload, started_by)
    VALUES (p_guild_id, 'core', 'post_message', jsonb_build_object('post_id', post_id), p_started_by)
    RETURNING id INTO job_id;
    PERFORM pg_notify('teabot_jobs', job_id::text);
    RETURN post_id;
END $$
"""


# What the runtime role may do in the plugin's schema: use its tables and sequences, now and as migrations add them.
RUNTIME_GRANTS = """
GRANT USAGE ON SCHEMA "{schema}" TO "{runtime}";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{runtime}";
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO "{runtime}";
ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO "{runtime}";
ALTER DEFAULT PRIVILEGES IN SCHEMA "{schema}" GRANT USAGE, SELECT ON SEQUENCES TO "{runtime}";
"""

# The server a plugin connection acts for. A reset setting reads back as '', so nullif makes an unscoped
# connection see no rows rather than fail (S6).
SCOPE = "nullif(current_setting('teabot.guild_id', true), '')::bigint"
SCOPED_TABLES = """
SELECT c.relname FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'guild_id' AND NOT a.attisdropped
WHERE n.nspname = $1 AND c.relkind IN ('r', 'p')
AND NOT EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid AND p.polname = 'teabot_server')
ORDER BY c.relname
"""


async def scope_tables(conn: AnyConn, naming: Naming, plugin_id: str) -> None:
    """Hold every table of the plugin to one server for its runtime role: a policy on `guild_id`, and the
    current server as `guild_id`'s default. The owner role, which runs migrations, is exempt, since the tables
    are not set to FORCE. Safe to repeat; run after each plugin's migrations, so new tables get it too (S6)."""
    role, schema = naming.plugin_role(plugin_id), naming.plugin_schema(plugin_id)
    runtime = naming.plugin_runtime_role(plugin_id)
    async with conn.transaction():
        await conn.execute(f'SET LOCAL ROLE "{role}"')
        for row in await conn.fetch(SCOPED_TABLES, schema):
            table = f'"{schema}"."{row["relname"]}"'
            await conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
            await conn.execute(
                f'CREATE POLICY teabot_server ON {table} TO "{runtime}" '
                f"USING (guild_id = {SCOPE}) WITH CHECK (guild_id = {SCOPE})"
            )
            await conn.execute(f"ALTER TABLE {table} ALTER COLUMN guild_id SET DEFAULT {SCOPE}")
        await conn.execute("RESET ROLE")


async def _apply(conn: Conn, naming: Naming, plugin_id: str, migration: MigrationFile, *, last: bool) -> None:
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
            # A released migration cannot change, so a column the member check names may be fixed by a later
            # one: that check reads the schema as the last pending migration leaves it.
            problems = await schema_problems(conn, naming.plugin_schema(plugin_id), members=last)
            if problems:
                raise MigrationError(f"{plugin_id}: " + "; ".join(problems))
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
        await _apply(conn, naming, plugin_id, migration, last=migration is pending[-1])
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
                await scope_tables(conn, naming, plugin.plugin_id)
            except (MigrationError, asyncpg.PostgresError) as exc:
                report.failed[plugin.plugin_id] = str(exc)
                log.error("plugin migration failed", extra={"plugin": plugin.plugin_id, "error": str(exc)})
    finally:
        await conn.execute("SELECT pg_advisory_unlock($1, 0)", MIGRATION_NS)
    return report
