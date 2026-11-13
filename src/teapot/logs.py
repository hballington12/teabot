"""Logging setup: readable lines in dev mode, JSON lines in production (implementation plan).

Both formats carry a record's `extra=` fields, so a reason passed that way is never lost.
"""

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Literal

# `color_message` is uvicorn's terminal-coloured copy of the message, not information of its own.
_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "color_message",
}


def _extras(record: logging.LogRecord) -> dict[str, object]:
    """The fields passed with `extra=`: anything not standard on a record and not private."""
    return {k: v for k, v in vars(record).items() if k not in _STANDARD_ATTRS and not k.startswith("_")}


class JsonFormatter(logging.Formatter):
    """One JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_extras(record),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    """A readable line, with extras appended as `key=value`."""

    def __init__(self) -> None:
        super().__init__("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        extras = " ".join(f"{k}={v!r}" for k, v in _extras(record).items())
        return f"{line} {extras}" if extras else line


def setup_logging(level: str, fmt: Literal["text", "json"]) -> None:
    """Configure the root logger once. Calling it again replaces the handler."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("discord").setLevel(max(logging.INFO, root.level))
