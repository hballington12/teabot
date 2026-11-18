"""Member labels: short strings a plugin keeps about members, which filters and role rules match.

A plugin that declares `Plugin(..., writes=["labels"])` writes its labels for the whole server at once with
`ctx.labels.replace_all`. The core gives them no meaning: `in_clan` or `rank:sapphire` mean what the plugin says.
Filters read them with `MemberFilter(labels_from=..., labels_any=[...])`, and only while they are fresh, so a plugin
that stops syncing stops counting rather than leaving old labels in force.
"""

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from typing import Protocol

WRITES = frozenset({"labels"})
"""What `Plugin(..., writes=[...])` may name."""
MAX_LABELS = 32
"""How many labels one plugin may keep for one member."""
MAX_LENGTH = 64
"""How long one label may be."""
DEFAULT_FRESH = timedelta(days=1)
"""How long a plugin's labels count after the data they came from, unless it declares otherwise."""
MAX_FRESH = timedelta(days=7)
"""The longest freshness window a plugin may declare."""


class LabelError(ValueError):
    """Labels the core refuses: too many for a member, too long, empty or with spaces."""


class Labels(Protocol):
    """The plugin's labels in one server, for a plugin that declares `writes=["labels"]`."""

    async def replace_all(self, labels: Mapping[int, Iterable[str]], /, *, as_of: datetime) -> int:
        """Replace every label the plugin keeps in this server with `labels`, member ID to that member's labels, in
        one transaction. A member left out loses theirs. `as_of` is how fresh the data behind them is, such as the
        plugin's last successful fetch, which decides how long they count. Returns how many members' labels
        changed. Raises `DirectoryUnavailable` while the server's member directory is not ready."""
        ...


def checked(values: Iterable[str]) -> tuple[str, ...]:
    """One member's labels, sorted and without repeats, or `LabelError` saying what is wrong."""
    found = tuple(sorted(set(values)))
    if len(found) > MAX_LABELS:
        raise LabelError(f"{len(found)} labels for one member; a plugin keeps at most {MAX_LABELS}")
    for label in found:
        if not label or len(label) > MAX_LENGTH or any(c.isspace() for c in label):
            raise LabelError(f"{label!r} is not a label: 1 to {MAX_LENGTH} characters, with no spaces")
    return found
