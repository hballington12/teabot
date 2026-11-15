"""`teabot dev`: what it watches, and how it reaches an instance's Compose Postgres."""

from pathlib import Path

import pytest
from watchfiles import Change

from teabot.cli.dev import CodeFilter, command, compose_env, watched


def test_in_an_instance_folder_it_reaches_the_compose_postgres(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    (tmp_path / ".env").write_text("TEABOT_DB_OWNER_PASSWORD=s3cret\nTEABOT_DB_PORT=55999\n")
    assert compose_env({}, tmp_path) == {
        "TEABOT_DB_HOST": "127.0.0.1",
        "TEABOT_DB_PORT": "55999",
        "TEABOT_DB_OWNER_PASSWORD": "s3cret",
    }


def test_the_environment_wins_and_outside_an_instance_nothing_is_set(tmp_path: Path) -> None:
    (tmp_path / "compose.yaml").write_text("services: {}\n")
    assert compose_env({"TEABOT_DB_PORT": "6000", "TEABOT_DB_HOST": "db"}, tmp_path) == {}
    assert compose_env({}, tmp_path / "elsewhere") == {}


def test_it_watches_the_plugins_folder_and_the_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "plugins").mkdir()
    (tmp_path / "teabot.env").write_text("")
    assert watched([], Path("teabot.env")) == [Path("plugins"), Path("teabot.env")]


def test_only_code_migrations_and_settings_restart_it() -> None:
    keep = CodeFilter()
    assert keep(Change.modified, "/x/plugins/polls/src/teabot_polls/__init__.py")
    assert keep(Change.added, "/x/plugins/polls/src/teabot_polls/migrations/0002_more.sql")
    assert not keep(Change.modified, "/x/plugins/polls/.venv/lib/site.pyc")
    assert not keep(Change.modified, "/x/plugins/polls/notes.txt")


def test_it_runs_teabot_run_with_the_env_file() -> None:
    assert command(Path("teabot.env")).endswith("-m teabot run --env-file teabot.env")
