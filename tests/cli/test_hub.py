"""`teabot hub`: reading the catalogue, finding plugins, and what an instance has installed from it."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from teabot.cli import app, hub

COMMIT, NEWER = "9db374fc205c5aae1f99bd5fd127266076f40ec8", "1" * 40
WOM: dict[str, Any] = {
    "id": "wom",
    "package": "teabot-wom",
    "version": "1.0.0",
    "description": "Wise Old Man lookups",
    "repository": "https://github.com/someone/teabot-wom",
    "commit": NEWER,
    "requirement": f"teabot-wom @ git+https://github.com/someone/teabot-wom.git@{NEWER}",
    "external_connections": "api.wiseoldman.net",
    "dependencies": [],
    "teabot": ">=1.4,<2",
}


def served(plugins: list[dict[str, Any]]) -> httpx.MockTransport:
    return httpx.MockTransport(lambda _: httpx.Response(200, text=json.dumps({"plugins": plugins})))


@pytest.fixture
def with_catalogue(monkeypatch: pytest.MonkeyPatch) -> None:
    real = hub.catalogue

    def from_test(url: str, transport: httpx.BaseTransport | None = None) -> dict[str, hub.Listed]:
        return real(url, served([WOM]))

    monkeypatch.setattr(hub, "catalogue", from_test)


def test_the_catalogue_is_read_by_id() -> None:
    found = hub.catalogue("https://hub.example/catalogue.json", served([WOM]))
    assert (
        found["wom"].requirement.endswith(NEWER) and found["wom"].external_connections == "api.wiseoldman.net"
    )


def test_search_and_show_describe_the_plugin(with_catalogue: None) -> None:
    runner = CliRunner()
    assert "Wise Old Man lookups" in runner.invoke(app, ["hub", "search", "wise"]).output
    assert "No plugins match." in runner.invoke(app, ["hub", "search", "raids"]).output
    shown = runner.invoke(app, ["hub", "show", "wom"]).output
    assert "api.wiseoldman.net" in shown and f'uv add "{WOM["requirement"]}"' in shown


def test_an_unlisted_plugin_is_told(with_catalogue: None) -> None:
    result = CliRunner().invoke(app, ["hub", "show", "nope"])
    assert result.exit_code == 1 and "lists no plugin called nope" in result.output


def test_outdated_compares_installed_commits_with_the_catalogue(
    with_catalogue: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'mine'\ndependencies = [\n"
        f"  'teabot>=1.4,<2',\n  'teabot-wom @ git+https://github.com/someone/teabot-wom.git@{COMMIT}',\n"
        f"  'teabot-gone @ git+https://github.com/someone/teabot-gone.git@{COMMIT}',\n]\n"
    )
    shown = CliRunner().invoke(app, ["hub", "outdated"]).output
    assert f"{COMMIT[:12]} -> {NEWER[:12]}: uv run teabot hub add wom" in shown
    assert "teabot-gone" in shown and "no longer listed" in shown
