"""`teabot hub` and its catalogue: versions by teabot release, finding plugins, and syncing an instance."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from teabot import catalogue
from teabot.catalogue import Listed, parse, plan_sync
from teabot.cli import app

OLD, NEW, FUTURE = "1" * 40, "2" * 40, "3" * 40


def version(commit: str, teabot: str, number: str) -> dict[str, Any]:
    return {
        "commit": commit,
        "version": number,
        "teabot": teabot,
        "requirement": f"teabot-wom @ git+https://github.com/someone/teabot-wom.git@{commit}",
        "external_connections": "api.wiseoldman.net",
        "dependencies": [],
    }


WOM: dict[str, Any] = {
    "id": "wom",
    "package": "teabot-wom",
    "description": "Wise Old Man lookups",
    "repository": "https://github.com/someone/teabot-wom",
    **version(FUTURE, ">=9,<10", "3.0.0"),
    "versions": [
        version(FUTURE, ">=9,<10", "3.0.0"),
        version(NEW, ">=1.4,<2", "2.0.0"),
        version(OLD, ">=1.0,<2", "1.0.0"),
    ],
}


def listed() -> dict[str, Listed]:
    return parse({"plugins": [WOM]})


def test_each_teabot_gets_the_newest_version_it_runs() -> None:
    wom = listed()["wom"]
    assert wom.for_teabot("1.5.0.dev0") is not None and wom.for_teabot("1.5.0.dev0").commit == NEW  # type: ignore[union-attr]
    assert wom.for_teabot("1.2.0").commit == OLD  # type: ignore[union-attr]
    assert wom.for_teabot("3.0.0") is None


def test_a_catalogue_without_versions_gives_each_plugin_its_one() -> None:
    old = {k: v for k, v in WOM.items() if k != "versions"}
    assert [v.commit for v in parse({"plugins": [old]})["wom"].versions] == [FUTURE]


def test_sync_installs_what_is_missing_moves_what_is_old_and_names_the_delisted() -> None:
    found = plan_sync(listed(), {"teabot-wom": OLD, "teabot-gone": OLD}, teabot_version="1.5.0")
    assert [(c.plugin.id, c.to.commit, c.was) for c in found.changes] == [("wom", NEW, OLD)]
    assert found.delisted == ("teabot-gone",)
    assert plan_sync(listed(), {"teabot-wom": NEW}, teabot_version="1.5.0").changes == ()
    assert plan_sync(listed(), {}, skip=frozenset({"wom"}), teabot_version="1.5.0").changes == ()
    assert [p.id for p in plan_sync(listed(), {}, teabot_version="3.0").too_new] == ["wom"]


@pytest.fixture
def with_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    def served(url: str = "", transport: httpx.BaseTransport | None = None) -> dict[str, Listed]:
        body = json.dumps({"plugins": [WOM]})
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body))) as client:
            return parse(client.get("https://hub.example/catalogue.json").json())

    monkeypatch.setattr(catalogue, "fetch", served)


def test_search_and_show_describe_the_version_this_teabot_runs(with_catalogue: None) -> None:
    runner = CliRunner()
    assert "2.0.0" in runner.invoke(app, ["hub", "search", "wise"]).output
    shown = runner.invoke(app, ["hub", "show", "wom"]).output
    assert "api.wiseoldman.net" in shown and NEW in shown


def test_sync_check_says_what_would_change_and_exits_1(
    with_catalogue: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        f"[project]\nname = 'mine'\ndependencies = ['teabot-wom @ git+https://github.com/someone/teabot-wom.git@{OLD}']\n"
    )
    result = CliRunner().invoke(app, ["hub", "sync", "--check"])
    assert result.exit_code == 1
    assert f"move from {OLD[:12]} to 2.0.0 at {NEW[:12]}" in result.output


def test_outdated_compares_installed_commits_with_the_catalogue(
    with_catalogue: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'mine'\ndependencies = [\n"
        f"  'teabot-wom @ git+https://github.com/someone/teabot-wom.git@{OLD}',\n"
        f"  'teabot-gone @ git+https://github.com/someone/teabot-gone.git@{OLD}',\n]\n"
    )
    shown = CliRunner().invoke(app, ["hub", "outdated"]).output
    assert f"{OLD[:12]} -> {NEW[:12]}: uv run teabot hub add wom" in shown
    assert "teabot-gone" in shown and "no longer listed" in shown


def test_a_plugin_uv_add_wrote_into_its_sources_is_found(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'mine'\ndependencies = ['teabot>=1.4,<2', 'teabot-wom']\n\n"
        f"[tool.uv.sources]\nteabot-wom = {{ git = 'https://github.com/someone/teabot-wom.git', rev = '{OLD}' }}\n"
        "teabot-local = { workspace = true }\n"
    )
    assert catalogue.installed(tmp_path / "pyproject.toml") == {"teabot-wom": OLD}
