"""Small edits to an env file that keep every other line as it was."""

from pathlib import Path


def read_values(path: Path) -> dict[str, str]:
    """The `NAME=value` pairs in the file, ignoring comments and blank lines."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep and not line.lstrip().startswith("#"):
            values[name.strip()] = value.strip()
    return values


def set_values(path: Path, updates: dict[str, str]) -> None:
    """Replace the named lines in place, append the rest, and keep the file private to its owner."""
    lines = path.read_text().splitlines() if path.exists() else []
    pending = dict(updates)
    for index, line in enumerate(lines):
        name = line.partition("=")[0].strip()
        if name in pending and not line.lstrip().startswith("#"):
            lines[index] = f"{name}={pending.pop(name)}"
    lines.extend(f"{name}={value}" for name, value in pending.items())
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)
