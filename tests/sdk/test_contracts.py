"""The import-linter contracts of D45 name every internal module, so a new one cannot slip past them."""

import pkgutil
import tomllib
from pathlib import Path

import pytest

import teabot

PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"


def internal_modules() -> set[str]:
    """Every top-level module of `teabot` but the SDK and the package's entry point."""
    names = {f"teabot.{m.name}" for m in pkgutil.iter_modules(teabot.__path__)}
    return names - {"teabot.sdk", "teabot.__main__"}


@pytest.mark.parametrize("source", ["teabot.sdk", "teabot.plugins"])
def test_a_contract_forbids_every_internal_module(source: str) -> None:
    contracts = tomllib.loads(PYPROJECT.read_text())["tool"]["importlinter"]["contracts"]
    (contract,) = [c for c in contracts if source in c["source_modules"]]
    assert internal_modules() - set(contract["forbidden_modules"]) - {source} == set()
