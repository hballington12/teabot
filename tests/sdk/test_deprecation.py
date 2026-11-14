"""The deprecation helper (D45): an old SDK name keeps working, with a warning, for a minor release first."""

import warnings
from types import ModuleType

import pytest

from teabot.sdk.deprecation import Renamed, deprecated_names, warn_deprecated


def module_with_a_renamed_name() -> ModuleType:
    module = ModuleType("teabot_fake_sdk")
    module.NewName = object()  # type: ignore[attr-defined]
    module.__getattr__ = deprecated_names(module.__dict__, {"OldName": Renamed("NewName", since="1.2")})  # type: ignore[attr-defined]
    return module


def test_an_old_name_returns_the_new_one_with_a_warning() -> None:
    module = module_with_a_renamed_name()
    with pytest.warns(DeprecationWarning) as caught:
        found = module.OldName
    assert found is module.NewName
    assert str(caught[0].message) == (
        "teabot_fake_sdk.OldName is deprecated since 1.2 and will be removed in 2.0: use NewName"
    )


def test_the_warning_points_at_the_plugin_that_used_the_old_name() -> None:
    module = module_with_a_renamed_name()
    with pytest.warns(DeprecationWarning) as caught:
        module.OldName  # noqa: B018
    assert caught[0].filename == __file__


def test_a_name_that_never_existed_is_still_an_attribute_error() -> None:
    module = module_with_a_renamed_name()
    with warnings.catch_warnings(), pytest.raises(AttributeError, match="has no attribute 'Missing'"):
        warnings.simplefilter("error")
        module.Missing  # noqa: B018


def test_a_deprecated_argument_or_behaviour_warns_the_same_way() -> None:
    def old_style() -> None:
        warn_deprecated("passing colour as an int", since="1.3", instead="a colour name")

    with pytest.warns(
        DeprecationWarning, match="^passing colour as an int is deprecated since 1.3"
    ) as caught:
        old_style()
    assert caught[0].filename == __file__
