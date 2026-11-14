"""`teabot new-plugin` (D45): a package that loads, migrates and runs as it is written."""

import importlib
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from typer.testing import CliRunner

from teabot.cli import app
from teabot.cli.new_plugin import teabot_range
from teabot.testing import PluginHarness

FILES = [
    "README.md",
    "pyproject.toml",
    "src/teabot_scaffolded/__init__.py",
    "src/teabot_scaffolded/migrations/0001_greetings.sql",
    "src/teabot_scaffolded/py.typed",
    "tests/test_scaffolded.py",
    "tests/test_scaffolded_snapshot.py",
]


def new_plugin(tmp_path: Path, plugin_id: str = "scaffolded") -> Any:
    return CliRunner().invoke(app, ["new-plugin", plugin_id, "--into", str(tmp_path / "plugins")])


@pytest.fixture
def scaffolded(tmp_path: Path) -> Iterator[ModuleType]:
    """The generated package, imported from where it was written."""
    assert new_plugin(tmp_path).exit_code == 0
    src = str(tmp_path / "plugins/scaffolded/src")
    sys.path.insert(0, src)
    try:
        yield importlib.import_module("teabot_scaffolded")
    finally:
        sys.path.remove(src)
        sys.modules.pop("teabot_scaffolded", None)


def test_it_writes_the_package(tmp_path: Path) -> None:
    result = new_plugin(tmp_path)
    assert result.exit_code == 0, result.output
    root = tmp_path / "plugins/scaffolded"
    assert sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()) == FILES
    assert 'scaffolded = "teabot_scaffolded:plugin"' in (root / "pyproject.toml").read_text()
    assert "External connections: none" in (root / "README.md").read_text()
    assert 'dependencies = ["teabot>=1.0,<2"]' in (root / "pyproject.toml").read_text()
    assert "/plugins enable plugin:scaffolded" in result.output
    assert f"uv run --env-file .env --package teabot-scaffolded pytest {root}" in result.output


async def test_the_scaffolded_plugin_loads_migrates_and_runs(
    scaffolded: ModuleType, teabot_harness: Any
) -> None:
    harness: PluginHarness = await teabot_harness(scaffolded.plugin)
    assert await harness.invoke("scaffolded.hello", {}) == scaffolded.Greeted(times=1)
    assert await harness.admin.fetchval("SELECT greeting FROM plugin_scaffolded.greetings") == "hello"


def test_the_scaffolded_code_passes_ruff(tmp_path: Path) -> None:
    new_plugin(tmp_path)
    root = tmp_path / "plugins/scaffolded"
    for check in (["check"], ["format", "--check"]):
        done = subprocess.run(
            [sys.executable, "-m", "ruff", *check, "--isolated", "--line-length", "110", "."],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        assert done.returncode == 0, done.stdout


@pytest.mark.parametrize("plugin_id", ["Bad-Id", "x", "audit"])
def test_an_id_that_breaks_d46_or_is_reserved_is_refused(tmp_path: Path, plugin_id: str) -> None:
    result = new_plugin(tmp_path, plugin_id)
    assert result.exit_code == 1
    assert "plugin id" in result.stderr
    assert not (tmp_path / "plugins").exists()


def test_an_id_an_installed_plugin_has_is_refused(tmp_path: Path) -> None:
    result = new_plugin(tmp_path, "giveaways")
    assert result.exit_code == 1
    assert "the installed package teabot already has a plugin with the id giveaways" in result.stderr
    assert not (tmp_path / "plugins").exists()


def test_an_existing_directory_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / "plugins/scaffolded").mkdir(parents=True)
    result = new_plugin(tmp_path)
    assert result.exit_code == 1
    assert "already exists" in result.stderr
    assert list((tmp_path / "plugins/scaffolded").iterdir()) == []


@pytest.mark.parametrize(
    ("version", "expected"),
    [("1.0.2", "teabot>=1.0,<2"), ("1.1.0.dev0", "teabot>=1.0,<2"), ("2.3.0", "teabot>=2.0,<3")],
)
def test_a_new_plugin_accepts_its_whole_major_version(version: str, expected: str) -> None:
    assert teabot_range(version) == expected
