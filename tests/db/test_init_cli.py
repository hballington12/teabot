"""`teapot init` against a real database (WP1.3)."""

import asyncio
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from teapot.cli import app
from teapot.db.naming import Naming
from teapot.db.types import Conn
from teapot.envfile import read_values


async def test_init_generates_passwords_and_roles(env_file: Path, admin: Conn, naming: Naming) -> None:
    result = await asyncio.to_thread(CliRunner().invoke, app, ["init", "--env-file", str(env_file)])
    assert result.exit_code == 0, result.output
    values = read_values(env_file)
    assert len(values["TEAPOT_DB_APP_PASSWORD"]) >= 32
    assert len(values["TEAPOT_DB_PLUGINS_PASSWORD"]) >= 32
    assert f"created role {naming.app_role}" in result.output
    roles = await admin.fetch("SELECT rolname FROM pg_roles WHERE rolname LIKE $1", f"{naming.prefix}\\_%")
    assert {r["rolname"] for r in roles} == {naming.app_role, naming.plugins_role}


async def test_init_twice_keeps_passwords(env_file: Path) -> None:
    runner = CliRunner()
    await asyncio.to_thread(runner.invoke, app, ["init", "--env-file", str(env_file)])
    first = read_values(env_file)
    second_run = await asyncio.to_thread(runner.invoke, app, ["init", "--env-file", str(env_file)])
    assert second_run.exit_code == 0, second_run.output
    assert read_values(env_file) == first
    assert "generated" not in second_run.output


async def test_init_accepts_an_admin_user_and_does_not_warn(
    env_file: Path, owner_kwargs: dict[str, Any]
) -> None:
    args = [
        "init",
        "--env-file",
        str(env_file),
        "--admin-user",
        owner_kwargs["user"],
        "--admin-password",
        owner_kwargs["password"],
    ]
    result = await asyncio.to_thread(CliRunner().invoke, app, args)
    assert result.exit_code == 0, result.output
    assert "warning" not in result.output


async def test_init_warns_when_set_config_cannot_be_revoked(
    env_file: Path, admin: Conn, naming: Naming, owner_kwargs: dict[str, Any]
) -> None:
    owner, database = f"{naming.prefix}_owner", owner_kwargs["database"]
    await admin.execute(f"CREATE ROLE \"{owner}\" LOGIN CREATEROLE PASSWORD 'o'")
    await admin.execute(f'ALTER DATABASE "{database}" OWNER TO "{owner}"')
    try:
        args = ["init", "--env-file", str(env_file), "--admin-user", owner, "--admin-password", "o"]
        result = await asyncio.to_thread(CliRunner().invoke, app, args)
        assert result.exit_code == 0, result.output
        assert "warning: set_config is still executable by PUBLIC" in result.output
    finally:
        await admin.execute(f'ALTER DATABASE "{database}" OWNER TO "{owner_kwargs["user"]}"')
