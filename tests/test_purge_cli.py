"""`teapot plugins purge` (WP3.3, D7): the prompt, the outcome, and the refusal while loaded."""

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner, Result

from teapot.cli import app
from teapot.cli.plugins import describe
from teapot.core.audit import OPERATOR, audit_embed
from teapot.core.lifecycle import PurgePlan
from teapot.core.processes import open_lock_connection
from teapot.db.migrate import PluginMigrations, migrate
from teapot.db.naming import Naming
from teapot.db.pool import Login, Pools
from teapot.db.types import Conn


async def installed(admin: Conn, naming: Naming, tmp_path: Path) -> None:
    directory = tmp_path / "alpha"
    directory.mkdir()
    (directory / "0001_t.sql").write_text("CREATE TABLE entries (guild_id bigint);")
    await migrate(admin, naming, [PluginMigrations("alpha", directory)])


async def purge(env_file: Path, answer: str) -> Result:
    args = ["plugins", "purge", "alpha", "--env-file", str(env_file)]
    return await asyncio.to_thread(CliRunner().invoke, app, args, input=answer)


async def schema_left(admin: Conn) -> int:
    return await admin.fetchval("SELECT count(*) FROM pg_namespace WHERE nspname = 'plugin_alpha'")


async def test_yes_purges(env_file: Path, admin: Conn, naming: Naming, pools: Pools, tmp_path: Path) -> None:
    await installed(admin, naming, tmp_path)
    result = await purge(env_file, "y\n")
    assert result.exit_code == 0, result.output
    assert "table entries: 0 rows" in result.output and "Purged alpha." in result.output
    assert await schema_left(admin) == 0


async def test_no_changes_nothing(
    env_file: Path, admin: Conn, naming: Naming, pools: Pools, tmp_path: Path
) -> None:
    await installed(admin, naming, tmp_path)
    result = await purge(env_file, "n\n")
    assert result.exit_code == 0, result.output
    assert "Nothing was changed." in result.output
    assert await schema_left(admin) == 1


async def test_a_loaded_plugin_is_refused(
    env_file: Path, admin: Conn, naming: Naming, pools: Pools, tmp_path: Path, owner_login: Login
) -> None:
    await installed(admin, naming, tmp_path)
    lock = await open_lock_connection(owner_login, lambda: None)
    await lock.take_plugins(["alpha"])
    try:
        result = await purge(env_file, "y\n")
    finally:
        await lock.close()
    assert result.exit_code == 1
    assert "Refused: a running process has alpha loaded" in result.output
    assert await schema_left(admin) == 1


def test_the_prompt_lists_what_goes() -> None:
    plan = PurgePlan("alpha", {}, {1: True, 2: False}, jobs=3)
    assert describe(plan) == [
        "Purging alpha deletes, everywhere:",
        "  no tables",
        "  its settings in 2 servers, enabled in 1",
        "  3 queued jobs, and its migration history, schema and role",
    ]


def test_the_log_channel_names_the_operator() -> None:
    row = {
        "id": 1,
        "action": "plugins.purge",
        "outcome": "ok",
        "user_id": OPERATOR,
        "surface": "cli",
        "input": "{}",
        "error": None,
        "time": datetime.now(UTC),
    }
    member = audit_embed(row).fields[0]  # type: ignore[arg-type]
    assert (member.name, member.value) == ("Member", "the operator")
