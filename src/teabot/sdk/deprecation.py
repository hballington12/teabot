"""Deprecating part of the SDK (D45). For the SDK's maintainers, not for plugins.

A breaking change to `teabot.sdk` waits for a major release, and the old form keeps working with a
`DeprecationWarning` for at least one minor release first. The warning names the version that removes it,
and points at the plugin's line that used the old form, so its author sees where to change.

- A renamed name: give the module a `__getattr__` from `deprecated_names`, which returns the new object.
- An old argument or behaviour: call `warn_deprecated` where the old form is handled.
"""

import warnings
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Renamed:
    """An old name that is now `new`, deprecated since the minor release `since`, such as `1.2`."""

    new: str
    since: str


def removed_in(since: str) -> str:
    """The major release after `since`, which may remove what it deprecated."""
    return f"{int(since.split('.', maxsplit=1)[0]) + 1}.0"


def deprecated_names(namespace: Mapping[str, Any], renamed: Mapping[str, Renamed]) -> Callable[[str], Any]:
    """A module `__getattr__` that answers each old name with its new object, and warns."""
    module = namespace["__name__"]

    def __getattr__(name: str) -> Any:
        if name not in renamed:
            raise AttributeError(f"module {module!r} has no attribute {name!r}")
        old = renamed[name]
        warnings.warn(
            f"{module}.{name} is deprecated since {old.since} and will be removed in {removed_in(old.since)}:"
            f" use {old.new}",
            DeprecationWarning,
            stacklevel=2,
        )
        return namespace[old.new]

    return __getattr__


def warn_deprecated(what: str, *, since: str, instead: str) -> None:
    """Warn that `what` is deprecated, from the SDK function that handles it, pointing at that function's
    caller."""
    warnings.warn(
        f"{what} is deprecated since {since} and will be removed in {removed_in(since)}: use {instead}",
        DeprecationWarning,
        stacklevel=3,
    )
