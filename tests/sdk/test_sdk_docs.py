"""Every public name of `teapot.sdk` is documented (D45), since plugin authors read the SDK and nothing else."""

import dataclasses
import inspect
from typing import Any

import pytest

from teapot import sdk

CLASSES = [getattr(sdk, n) for n in sdk.__all__ if inspect.isclass(getattr(sdk, n))]


def own_members(cls: type) -> dict[str, Any]:
    """The public methods and properties `cls` defines itself."""
    return {
        name: value
        for name, value in vars(cls).items()
        if not name.startswith("_") and (inspect.isfunction(value) or isinstance(value, property))
    }


def test_the_package_docstring_lists_every_public_name() -> None:
    doc = sdk.__doc__ or ""
    assert [n for n in sdk.__all__ if f"`{n}`" not in doc] == []


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
def test_every_public_class_has_its_own_docstring(cls: type) -> None:
    assert cls.__dict__.get("__doc__")


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
def test_every_member_is_documented(cls: type) -> None:
    undocumented = [n for n, v in own_members(cls).items() if not inspect.getdoc(v)]
    assert undocumented == []


@pytest.mark.parametrize("cls", [c for c in CLASSES if dataclasses.is_dataclass(c)], ids=lambda c: c.__name__)
def test_every_dataclass_field_is_described_in_its_class_docstring(cls: type) -> None:
    doc = cls.__doc__ or ""
    assert [f.name for f in dataclasses.fields(cls) if f"`{f.name}`" not in doc] == []
