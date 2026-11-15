"""`teabot init` against a real database."""

import asyncio
import base64
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from typer.testing import CliRunner

from teabot.cli import app
from teabot.cli.init import application_id
from teabot.db.naming import Naming
from teabot.db.types import Conn
from teabot.envfile import read_values, set_values


async def test_init_generates_passwords_and_roles(env_file: Path, admin: Conn, naming: Naming) -> None:
    result = await asyncio.to_thread(CliRunner().invoke, app, ["init", "--env-file", str(env_file)])
    assert result.exit_code == 0, result.output
    values = read_values(env_file)
    assert len(values["TEABOT_DB_APP_PASSWORD"]) >= 32
    assert len(values["TEABOT_DB_PLUGINS_PASSWORD"]) >= 32
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


async def test_rotate_replaces_both_passwords_and_the_roles_take_them(
    env_file: Path, admin: Conn, naming: Naming
) -> None:
    runner = CliRunner()
    await asyncio.to_thread(runner.invoke, app, ["init", "--env-file", str(env_file)])
    first = read_values(env_file)
    rotated = await asyncio.to_thread(runner.invoke, app, ["init", "--env-file", str(env_file), "--rotate"])
    assert rotated.exit_code == 0, rotated.output
    now = read_values(env_file)
    for name in ("TEABOT_DB_APP_PASSWORD", "TEABOT_DB_PLUGINS_PASSWORD"):
        assert now[name] != first[name]
    assert "Restart teabot now" in rotated.output
    host, port = admin._addr  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]
    database = admin._params.database  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]
    conn = await asyncpg.connect(
        host=host, port=port, database=database, user=naming.app_role, password=now["TEABOT_DB_APP_PASSWORD"]
    )
    await conn.close()


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


TOKEN = base64.urlsafe_b64encode(b"123456789012345678").decode().rstrip("=") + ".GhIjKl.secret-part"


@pytest.mark.parametrize(
    ("token", "expected"), [(TOKEN, 123456789012345678), ("", None), ("not-a-token", None), ("!!!.a.b", None)]
)
def test_the_application_id_is_the_tokens_first_part(token: str, expected: int | None) -> None:
    assert application_id(token) == expected


async def test_init_prints_the_discord_settings_with_the_invite(env_file: Path) -> None:
    set_values(env_file, {"TEABOT_DISCORD_TOKEN": TOKEN})
    result = await asyncio.to_thread(CliRunner().invoke, app, ["init", "--env-file", str(env_file)])
    assert result.exit_code == 0, result.output
    assert "Server Members Intent" in result.output
    assert (
        "https://discord.com/oauth2/authorize?client_id=123456789012345678"
        "&scope=bot+applications.commands&permissions=8"
    ) in result.output
    assert "below the owner's and senior staff roles" in result.output
    assert TOKEN not in result.output


async def test_without_a_token_the_invite_names_what_to_fill_in(env_file: Path) -> None:
    result = await asyncio.to_thread(CliRunner().invoke, app, ["init", "--env-file", str(env_file)])
    assert "client_id=<application id>" in result.output
