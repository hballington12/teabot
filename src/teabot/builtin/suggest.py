"""Suggestions for the built-in commands' options, as the member types."""

from collections.abc import Iterable

from teabot.sdk import Choice

SHOWN = 25


def matching[T: (str, int)](choices: Iterable[Choice[T]], typed: str) -> list[Choice[T]]:
    """The choices whose name holds what was typed, ignoring case, up to Discord's 25."""
    needle = typed.strip().lower()
    return [c for c in choices if needle in c.name.lower()][:SHOWN]
