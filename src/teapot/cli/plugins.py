"""`teapot plugins`: what the database knows about plugins (D34). `purge` arrives in WP3.3."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from teapot.core.processes import loaded_plugins
from teapot.db.pool import ConnectionInfo, Database, Login, open_pool
from teapot.settings import DEFAULT_ENV_FILE, Settings, load_settings

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


async def _overview_for(settings: Settings) -> tuple[int, list[PluginRow]]:
    info = ConnectionInfo(settings.db_host, settings.db_port, settings.db_name)
    pool = await open_pool(
        Login(info, settings.db_owner_user, settings.db_owner_password.get_secret_value()), 1
    )
    try:
        return await overview(Database(pool))
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
