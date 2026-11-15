"""`teabot check`: the review checklist, run against a plugin project's code."""

import importlib
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from teabot.cli import app
from teabot.lint import check_package, check_project
from teabot.testing import CheckFailed, HarnessFactory

GOOD_CODE = '''"""A plugin that does everything the checklist asks."""

from teabot.sdk import Context, Plugin

UPDATE = "UPDATE notes SET text = $2 WHERE guild_id = $1"
PROSE = "Set a reminder for later"
plugin = Plugin("good")


async def stamp(ctx: Context) -> str:
    return str(ctx.now)
'''
GOOD_SQL = """-- CURRENT_TIMESTAMP in a comment is fine.
CREATE TABLE notes (guild_id bigint NOT NULL, text text, at timestamptz DEFAULT now());
"""
GOOD_TEST = "from teabot.testing import PluginHarness\n"
README = "# good\n\n- External connections: none.\n"


def project(root: Path, code: str = GOOD_CODE, sql: str = GOOD_SQL, readme: str | None = README) -> Path:
    package = root / "src" / "teabot_good"
    (package / "migrations").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'teabot-good'\n")
    (package / "__init__.py").write_text(code)
    (package / "migrations" / "0001_notes.sql").write_text(sql)
    (root / "tests" / "test_good.py").write_text(GOOD_TEST)
    if readme is not None:
        (root / "README.md").write_text(readme)
    return root


def messages(root: Path) -> list[str]:
    return [p.message for p in check_project(root)]


def test_a_plugin_that_follows_the_checklist_passes(tmp_path: Path) -> None:
    assert check_project(project(tmp_path)) == []


def test_importing_teabots_internals_is_flagged_with_its_line(tmp_path: Path) -> None:
    root = project(tmp_path, code=GOOD_CODE + "from teabot.core.registry import Refused\nimport teabot.db\n")
    problems = check_project(root)
    assert [(p.line, p.message) for p in problems] == [
        (12, "imports teabot.core.registry; plugins import only teabot.sdk"),
        (13, "imports teabot.db; plugins import only teabot.sdk"),
    ]


def test_setting_a_setting_in_sql_is_flagged(tmp_path: Path) -> None:
    for sql in (
        "SET teabot.guild_id = '2'",
        "set role other",
        "RESET ALL",
        "SELECT set_config('x', 'y', false)",
    ):
        code = GOOD_CODE + f"BAD = {sql!r}\n"
        assert messages(project(tmp_path / sql.split()[0] / str(len(sql)), code=code)) == [
            "changes a setting with SET, RESET or set_config, which plugin SQL must not do"
        ], sql


def test_reading_the_clock_directly_is_flagged(tmp_path: Path) -> None:
    code = GOOD_CODE + (
        "import datetime\nimport time\n\nWHEN = datetime.datetime.now()\nTICK = time.time()\n"
        'LATE = "SELECT * FROM notes WHERE at < CURRENT_TIMESTAMP"\n'
    )
    sql = (
        GOOD_SQL
        + "CREATE TABLE later (guild_id bigint NOT NULL, at timestamptz DEFAULT CURRENT_TIMESTAMP);\n"
    )
    found = messages(project(tmp_path, code=code, sql=sql))
    assert found.count("reads the clock directly, which tests cannot move; use ctx.now") == 2
    assert found.count("uses CURRENT_TIMESTAMP, which tests cannot move; use now()") == 2


def test_a_readme_without_external_connections_is_flagged(tmp_path: Path) -> None:
    assert messages(project(tmp_path / "a", readme="# good\n")) == [
        'has no "External connections" section listing the hosts the plugin contacts'
    ]
    assert messages(project(tmp_path / "b", readme=None)) == [
        'the plugin has no README.md with an "External connections" section'
    ]


def test_the_command_prints_each_problem_and_fails(tmp_path: Path) -> None:
    root = project(tmp_path, code=GOOD_CODE + "import teabot.db\n")
    result = CliRunner().invoke(app, ["check", str(root)])
    assert result.exit_code == 1
    assert "__init__.py:12: imports teabot.db; plugins import only teabot.sdk" in result.output
    clean = CliRunner().invoke(app, ["check", str(project(tmp_path / "clean"))])
    assert (clean.exit_code, clean.output.strip()) == (0, "no problems found")


async def test_the_harness_checks_a_plugins_package_when_it_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, teabot_harness: HarnessFactory
) -> None:
    package = tmp_path / "teabot_sloppy"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from typing import Any\n\nimport teabot.db\nfrom teabot.sdk import Context, Plugin\n\n"
        'plugin = Plugin("sloppy")\n\n\n@plugin.action()\nasync def hi(ctx: Context[Any]) -> str:\n'
        '    """Say hi."""\n    return "hi"\n'
    )
    (tmp_path / "README.md").write_text("- External connections: none.\n")
    monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
    importlib.invalidate_caches()
    sloppy = importlib.import_module("teabot_sloppy").plugin
    with pytest.raises(CheckFailed, match=r"__init__\.py:3: imports teabot\.db"):
        await teabot_harness(sloppy)


def test_plugin_code_reaching_the_web_itself_is_flagged(tmp_path: Path) -> None:
    package = tmp_path / "teabot_web"
    package.mkdir()
    (package / "__init__.py").write_text("import requests\nfrom aiohttp import ClientSession\n")
    (package / "README.md").write_text("# web\n\n## External connections\n\nNone.\n")
    problems = [p.message for p in check_package(package)]
    assert sum("reach the web through ctx.http" in m for m in problems) == 2
