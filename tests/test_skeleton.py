"""Checks that the workspace, the CLI and the test database are wired up."""

from typing import Any

from typer.testing import CliRunner

import teabot
from teabot.cli import app


def test_version_is_set() -> None:
    assert teabot.__version__


def test_cli_prints_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"teabot {teabot.__version__}"


def test_database_is_postgres_16_or_later(teabot_pg: Any) -> None:
    with teabot_pg.cursor() as cur:
        cur.execute("SHOW server_version_num")
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) >= 160000
