"""Deleting one member's data (D11), for a member's request under Discord's developer policy.

Plugin columns of the type `teabot.member_id` hold members' IDs, so deletion finds them through the catalog, in
every plugin, with no plugin code: a row with the member in such a column is deleted, and the member is taken out
of a `teabot.member_id[]` column. In the core, their tokens, site sign-ins, unsent drafts, member directory rows
and history (D55) and member labels are deleted, and their ID is taken out of the audit log, the job and settings
records, and the directory's record of who invited, kicked or banned whom, which keep what was done but no longer
by whom.
"""

from dataclasses import dataclass, field

from teabot.db.naming import Naming
from teabot.db.types import AnyConn

PLUGIN_SCHEMAS = "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'plugin\\_%' ORDER BY nspname"
MEMBER_COLUMNS = """
SELECT c.relname, a.attname, a.atttypid = 'teabot.member_id[]'::regtype AS is_array FROM pg_attribute a
JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = $1 AND c.relkind IN ('r', 'p') AND NOT c.relispartition AND a.attnum > 0 AND NOT a.attisdropped
AND a.atttypid IN ('teabot.member_id'::regtype, 'teabot.member_id[]'::regtype)
ORDER BY 1, 2
"""
ANONYMOUS = 0
CORE_STEPS = (
    ("tokens", "DELETE FROM core.tokens WHERE user_id = $1 AND ($2::bigint IS NULL OR guild_id = $2)"),
    # A sign-in spans servers, so only deleting everywhere ends it.
    ("site sign-ins", "DELETE FROM core.web_sessions WHERE user_id = $1 AND $2::bigint IS NULL"),
    (
        "drafts",
        "DELETE FROM core.interaction_drafts WHERE user_id = $1 AND ($2::bigint IS NULL OR guild_id = $2)",
    ),
    (
        "audit log",
        f"UPDATE core.audit_log SET user_id = {ANONYMOUS} WHERE user_id = $1 AND ($2::bigint IS NULL OR guild_id = $2)",
    ),
    (
        "audit reads",
        f"UPDATE core.audit_reads SET user_id = {ANONYMOUS} "
        "WHERE user_id = $1 AND ($2::bigint IS NULL OR guild_id = $2)",
    ),
    (
        "jobs",
        "UPDATE core.jobs SET started_by = NULL WHERE started_by = $1 AND ($2::bigint IS NULL OR guild_id = $2)",
    ),
    (
        "settings",
        "UPDATE core.guild_plugins SET updated_by = NULL "
        "WHERE updated_by = $1 AND ($2::bigint IS NULL OR guild_id = $2)",
    ),
    (
        "member directory",
        "DELETE FROM core.members WHERE user_id = $1 AND ($2::bigint IS NULL OR guild_id = $2)",
    ),
    (
        "member labels",
        "DELETE FROM core.member_labels WHERE user_id = $1 AND ($2::bigint IS NULL OR guild_id = $2)",
    ),
    (
        "member history",
        "DELETE FROM core.member_events WHERE user_id = $1 AND ($2::bigint IS NULL OR guild_id = $2)",
    ),
    (
        "directory inviters",
        f"UPDATE core.members SET inviter_id = {ANONYMOUS} "
        "WHERE inviter_id = $1 AND ($2::bigint IS NULL OR guild_id = $2)",
    ),
    (
        "history actors",
        f"UPDATE core.member_events SET actor_id = {ANONYMOUS} "
        "WHERE actor_id = $1 AND ($2::bigint IS NULL OR guild_id = $2)",
    ),
    (
        "history inviters",
        f"""UPDATE core.member_events SET detail = detail || '{{"inviter_id": "{ANONYMOUS}"}}'
        WHERE kind = 'joined' AND detail->>'inviter_id' = $1::bigint::text AND ($2::bigint IS NULL OR guild_id = $2)""",
    ),
    (
        "deleted roles' holders",
        "UPDATE core.member_events "
        "SET detail = jsonb_set(detail, '{holders}', (detail->'holders') - $1::bigint::text) "
        "WHERE kind = 'role_deleted' AND detail->'holders' ? $1::bigint::text "
        "AND ($2::bigint IS NULL OR guild_id = $2)",
    ),
)


def quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _rows(status: str) -> int:
    """How many rows a DELETE or UPDATE status, such as `DELETE 3`, says it touched."""
    return int(status.rsplit(" ", 1)[-1])


@dataclass
class Deleted:
    """What deleting a member's data changed: rows per plugin table, and per core record."""

    plugins: dict[str, int] = field(default_factory=dict[str, int])
    core: dict[str, int] = field(default_factory=dict[str, int])

    @property
    def total(self) -> int:
        return sum(self.plugins.values()) + sum(self.core.values())


async def _plugin(
    conn: AnyConn, naming: Naming, schema: str, member: tuple[int, int | None], out: Deleted
) -> None:
    plugin_id = schema.removeprefix("plugin_")
    user_id, guild_id = member
    async with conn.transaction():
        await conn.execute(f'SET LOCAL ROLE "{naming.plugin_role(plugin_id)}"')
        for col in await conn.fetch(MEMBER_COLUMNS, schema):
            table, column = f"{quoted(schema)}.{quoted(col['relname'])}", quoted(col["attname"])
            scope = "AND ($2::bigint IS NULL OR guild_id = $2)"
            if col["is_array"]:
                sql = f"UPDATE {table} SET {column} = array_remove({column}, $1) WHERE $1 = ANY({column}) {scope}"
            else:
                sql = f"DELETE FROM {table} WHERE {column} = $1 {scope}"
            changed = _rows(await conn.execute(sql, user_id, guild_id))
            if changed:
                key = f"{plugin_id}.{col['relname']}"
                out.plugins[key] = out.plugins.get(key, 0) + changed


async def delete_member_data(
    conn: AnyConn, naming: Naming, user_id: int, guild_id: int | None = None
) -> Deleted:
    """Delete one member's data in every plugin and the core, in one server or, without `guild_id`, in all of
    them. Runs on the owner's connection; each plugin's rows are deleted as that plugin's role. Safe to repeat."""
    out = Deleted()
    for row in await conn.fetch(PLUGIN_SCHEMAS):
        await _plugin(conn, naming, row["nspname"], (user_id, guild_id), out)
    async with conn.transaction():
        for name, sql in CORE_STEPS:
            changed = _rows(await conn.execute(sql, user_id, guild_id))
            if changed:
                out.core[name] = changed
    return out
