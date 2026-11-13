"""Checks that the workspace, the CLI and the test database are wired up (WP1.1)."""

from typing import Any

from typer.testing import CliRunner

import teapot
from teapot.cli import app


def test_version_is_set() -> None:
    assert teapot.__version__


def test_cli_prints_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"teapot {teapot.__version__}"


def test_database_is_postgres_16_or_later(postgresql: Any) -> None:
    with postgresql.cursor() as cur:
        cur.execute("SHOW server_version_num")
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) >= 160000
