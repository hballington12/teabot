"""`teapot init` against a real database (WP1.3)."""

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from teapot.cli import app
from teapot.db.naming import Naming
from teapot.db.types import Conn
from teapot.envfile import read_values


@pytest.fixture
def env_file(
    tmp_path: Path, owner_kwargs: dict[str, Any], naming: Naming, monkeypatch: pytest.MonkeyPatch
) -> Path:
    for name in list(os.environ):
        if name.startswith("TEAPOT_"):
            monkeypatch.delenv(name)
    env = tmp_path / "teapot.env"
    env.write_text(
        f"TEAPOT_DB_HOST={owner_kwargs['host']}\n"
        f"TEAPOT_DB_PORT={owner_kwargs['port']}\n"
        f"TEAPOT_DB_NAME={owner_kwargs['database']}\n"
        f"TEAPOT_DB_OWNER_USER={owner_kwargs['user']}\n"
        f"TEAPOT_DB_OWNER_PASSWORD={owner_kwargs['password']}\n"
        f"TEAPOT_DB_ROLE_PREFIX={naming.prefix}\n"
    )
    return env


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
