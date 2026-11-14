"""The import-linter contracts of D45 name every internal module, so a new one cannot slip past them."""

import pkgutil
import tomllib
from pathlib import Path

import pytest

import teapot

PYPROJECT = Path(__file__).parents[2] / "pyproject.toml"


def internal_modules() -> set[str]:
    """Every top-level module of `teapot` but the SDK and the package's entry point."""
    names = {f"teapot.{m.name}" for m in pkgutil.iter_modules(teapot.__path__)}
    return names - {"teapot.sdk", "teapot.__main__"}


@pytest.mark.parametrize("source", ["teapot.sdk", "teapot_announcements"])
def test_a_contract_forbids_every_internal_module(source: str) -> None:
    contracts = tomllib.loads(PYPROJECT.read_text())["tool"]["importlinter"]["contracts"]
    (contract,) = [c for c in contracts if source in c["source_modules"]]
    assert internal_modules() - set(contract["forbidden_modules"]) == set()
