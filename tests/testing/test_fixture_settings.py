"""Where the test fixtures find Postgres: the environment first, then the instance's Compose `.env`."""

from pathlib import Path

import pytest

from teabot.testing.fixtures import setting


def test_the_compose_env_file_supplies_what_the_environment_does_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("# Compose\nTEABOT_DB_OWNER_PASSWORD=from-file\nTEABOT_DB_PORT=5999\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TEABOT_TEST_PG_PASSWORD", raising=False)
    monkeypatch.delenv("TEABOT_DB_OWNER_PASSWORD", raising=False)
    assert setting("TEABOT_TEST_PG_PASSWORD", "TEABOT_DB_OWNER_PASSWORD", default="teabot") == "from-file"
    monkeypatch.setenv("TEABOT_TEST_PG_PASSWORD", "from-env")
    assert setting("TEABOT_TEST_PG_PASSWORD", "TEABOT_DB_OWNER_PASSWORD", default="teabot") == "from-env"


def test_without_either_the_default_holds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TEABOT_TEST_PG_HOST", raising=False)
    assert setting("TEABOT_TEST_PG_HOST", default="127.0.0.1") == "127.0.0.1"
