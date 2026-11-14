"""How the loader finds a `Plugin` through its entry point: the id check, its version, and its whole package."""

import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from teabot.core.loader import discover
from teabot.sdk import Plugin

PACKAGE_INIT = """
from teabot.sdk import Plugin

plugin = Plugin("pkgd")
"""
PACKAGE_ACTIONS = '''
from typing import Any

from teabot.sdk import Context
from pkgd_example import plugin


@plugin.action()
async def hello(ctx: Context[Any]) -> str:
    """Say hello."""
    return "hi"
'''


@dataclass
class Dist:
    name: str
    version: str


@dataclass
class EntryPoint:
    name: str
    target: object
    dist: Dist
    module: str

    def load(self) -> object:
        return self.target


def test_an_entry_point_named_differently_from_its_plugin_is_refused() -> None:
    eps = [EntryPoint("beta", Plugin("alpha"), Dist("teabot-beta", "1.0.0"), "teabot_beta")]
    (candidate,) = discover(lambda _group: eps)
    assert candidate.plugin is None
    assert (
        candidate.error
        == "its entry point is named beta but the plugin's id is alpha; rename one so they match"
    )


def test_a_plugin_learns_its_version_and_imports_its_whole_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "pkgd_example"
    (package / "tests").mkdir(parents=True)
    (package / "migrations").mkdir()
    (package / "__init__.py").write_text(PACKAGE_INIT)
    (package / "actions.py").write_text(PACKAGE_ACTIONS)
    (package / "_private.py").write_text("raise RuntimeError('private modules are not imported')")
    (package / "tests" / "__init__.py").write_text("raise RuntimeError('tests are not imported')")
    monkeypatch.setattr(sys, "path", [str(tmp_path), *sys.path])
    importlib.invalidate_caches()
    target = importlib.import_module("pkgd_example").plugin
    eps = [EntryPoint("pkgd", target, Dist("teabot-pkgd", "2.5.0"), "pkgd_example")]
    (candidate,) = discover(lambda _group: eps)
    assert candidate.error is None and candidate.plugin is target
    assert (target.manifest.version, target.manifest.migrations) == ("2.5.0", package / "migrations")
    assert list(target.actions) == ["pkgd.hello"]
