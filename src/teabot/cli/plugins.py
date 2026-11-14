"""`teabot plugins`: what the database knows about plugins, and purging one (D7, D34)."""

import asyncio
import getpass
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from teabot.core.audit import AuditLog
from teabot.core.lifecycle import Purge, PurgePlan, PurgeRefused
from teabot.core.processes import loaded_plugins
from teabot.core.queue import Queue
from teabot.db.naming import Naming
from teabot.db.pool import ConnectionInfo, Database, Login, open_pool
from teabot.settings import DEFAULT_ENV_FILE, Settings, load_settings

app = typer.Typer(name="plugins", help="Inspect and manage installed plugins.", no_args_is_help=True)

KNOWN_PLUGINS = """
SELECT plugin_id, max(version) AS version FROM (
    SELECT plugin_id, version FROM core.migrations
    UNION ALL SELECT plugin_id, 0 FROM core.guild_plugins
) known GROUP BY plugin_id ORDER BY plugin_id
"""


@dataclass(frozen=True)
class PluginRow:
    plugin_id: str
    version: int
    loaded: bool


async def overview(db: Database) -> tuple[int, list[PluginRow]]:
    """The core's schema version, and each known plugin's version and load state."""
    versions = {r["plugin_id"]: r["version"] for r in await db.fetch(KNOWN_PLUGINS)}
    core_version = versions.pop("core")
    loaded = await loaded_plugins(db, versions)
    return core_version, [PluginRow(p, v, p in loaded) for p, v in versions.items()]


def _owner_login(settings: Settings) -> Login:
    info = ConnectionInfo(settings.db_host, settings.db_port, settings.db_name)
    return Login(info, settings.db_owner_user, settings.db_owner_password.get_secret_value())


async def _overview_for(settings: Settings) -> tuple[int, list[PluginRow]]:
    pool = await open_pool(_owner_login(settings), 1)
    try:
        return await overview(Database(pool))
    finally:
        await pool.close()


def describe(plan: PurgePlan) -> list[str]:
    """What the confirmation prompt shows before a purge."""
    lines = [f"Purging {plan.plugin_id} deletes, everywhere:"]
    lines += [f"  table {name}: {rows} rows" for name, rows in plan.tables.items()] or ["  no tables"]
    enabled = len(plan.enabled_in)
    lines.append(f"  its settings in {len(plan.servers)} servers, enabled in {enabled}")
    lines.append(f"  {plan.jobs} queued jobs, and its migration history, schema and role")
    return lines


def ask(plan: PurgePlan) -> bool:
    for line in describe(plan):
        typer.echo(line)
    return typer.confirm("This cannot be undone. Purge?", default=False)


async def _purge_for(settings: Settings, plugin_id: str) -> PurgePlan | None:
    pool = await open_pool(_owner_login(settings), 2)
    try:
        audit = AuditLog(Queue(Database(pool)))
        async with pool.acquire() as conn:
            naming = Naming(settings.db_role_prefix)
            return await Purge(conn, naming, audit)(plugin_id, operator=getpass.getuser(), confirm=ask)
    finally:
        await pool.close()


@app.command("list")
def list_plugins(
    env_file: Annotated[Path, typer.Option(help="The instance's env file.")] = DEFAULT_ENV_FILE,
) -> None:
    """Show each plugin's migration version and whether a running process has it loaded."""
    core_version, rows = asyncio.run(_overview_for(load_settings(env_file)))
    typer.echo(f"core schema at version {core_version}")
    for row in rows:
        typer.echo(f"{row.plugin_id:<32} {row.version:>4}  {'loaded' if row.loaded else 'not loaded'}")


@app.command("purge")
def purge(
    plugin_id: Annotated[str, typer.Argument(help="The plugin's id.")],
    env_file: Annotated[Path, typer.Option(help="The instance's env file.")] = DEFAULT_ENV_FILE,
) -> None:
    """Delete a plugin's schema, role and rows everywhere. Refused while a process has it loaded."""
    try:
        plan = asyncio.run(_purge_for(load_settings(env_file), plugin_id))
    except PurgeRefused as exc:
        typer.echo(f"Refused: {exc}.", err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Purged {plugin_id}." if plan else "Nothing was changed.")
