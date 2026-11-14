"""`teabot plugins list` (WP1.7): plugins, their migration versions, and whether any process has them loaded."""

import asyncio
from pathlib import Path

from typer.testing import CliRunner

from teabot.cli import app
from teabot.core.processes import open_lock_connection
from teabot.db.migrate import CORE_MIGRATIONS, PluginMigrations, migrate, read_files
from teabot.db.naming import Naming
from teabot.db.pool import Login, Pools
from teabot.db.types import Conn


async def test_lists_plugins_with_versions_and_load_state(
    env_file: Path, admin: Conn, naming: Naming, pools: Pools, owner_login: Login, tmp_path: Path
) -> None:
    for plugin_id, files in (("alpha", 2), ("beta", 1)):
        directory = tmp_path / plugin_id
        directory.mkdir()
        for n in range(1, files + 1):
            (directory / f"{n:04d}_m.sql").write_text(f"CREATE TABLE t{n} (guild_id bigint);")
        await migrate(admin, naming, [PluginMigrations(plugin_id, directory)])
    lock = await open_lock_connection(owner_login, lambda: None)
    await lock.take_plugins(["alpha"])
    try:
        result = await asyncio.to_thread(
            CliRunner().invoke, app, ["plugins", "list", "--env-file", str(env_file)]
        )
    finally:
        await lock.close()
    assert result.exit_code == 0, result.output
    lines = [line.split() for line in result.output.splitlines()]
    assert ["alpha", "2", "loaded"] in lines
    assert ["beta", "1", "not", "loaded"] in lines
    assert ["core", "schema", "at", "version", str(len(read_files(CORE_MIGRATIONS)))] in lines
