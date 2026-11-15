"""The event loop's watchdog (D33): it names the plugin that blocks the loop, and stops a process that stays blocked.

A heartbeat task runs on the loop. Each beat re-arms `faulthandler`'s timer, whose own C thread needs no GIL: if
the loop misses the hard limit, it dumps every thread's traceback and exits the process, even while a C extension
holds the GIL. systemd or Compose then restarts it, and the queue fails a job that keeps doing this (D31).

Before that, a Python thread notices a beat more than the soft limit late and logs the innermost plugin frame on
the loop's stack, with its file and line, once for each stall.
"""

import asyncio
import faulthandler
import logging
import sys
import threading
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from types import FrameType

from teabot.core.loader import GROUP

log = logging.getLogger(__name__)
BEAT_SECONDS = 0.5


def plugin_packages() -> dict[str, str]:
    """Each installed plugin's top package, by plugin id, from the entry points. This works before any plugin is
    imported, so a plugin that hangs while it is imported is named too."""
    return {ep.name: ep.value.split(":", 1)[0] for ep in entry_points(group=GROUP)}


def blamed(frame: FrameType | None, packages: dict[str, str]) -> tuple[str, str, int] | None:
    """The plugin, file and line of the innermost frame of `frame`'s stack that is a plugin's code."""
    while frame is not None:
        module = str(frame.f_globals.get("__name__", ""))
        for plugin_id, package in packages.items():
            if module == package or module.startswith(f"{package}."):
                return plugin_id, frame.f_code.co_filename, frame.f_lineno
        frame = frame.f_back
    return None


@dataclass
class Watchdog:
    """`soft` and `hard` are in seconds. `startup` is the hard limit until the first beat, which covers the
    plugins' imports and migrations."""

    soft: float
    hard: float
    startup: float
    packages: dict[str, str] = field(default_factory=dict[str, str])
    last_beat: float = field(default_factory=time.monotonic)
    _loop_thread: int = 0
    _stopped: threading.Event = field(default_factory=threading.Event)

    def arm(self) -> None:
        """Start watching, from the loop's thread, before plugins load."""
        self._loop_thread = threading.get_ident()
        self.last_beat = time.monotonic()
        faulthandler.dump_traceback_later(self.startup, exit=True)
        threading.Thread(target=self._watch, name="teabot-watchdog", daemon=True).start()

    async def beat(self) -> None:
        """The heartbeat. Runs on the loop until cancelled."""
        try:
            while True:
                self.last_beat = time.monotonic()
                faulthandler.dump_traceback_later(self.hard, exit=True)
                await asyncio.sleep(BEAT_SECONDS)
        finally:
            self.disarm()

    def disarm(self) -> None:
        self._stopped.set()
        faulthandler.cancel_dump_traceback_later()

    def stall(self) -> float:
        """How long the loop has gone past its beat."""
        return time.monotonic() - self.last_beat - BEAT_SECONDS

    def _watch(self) -> None:
        reported = False
        while not self._stopped.wait(self.soft / 2):
            late = self.stall()
            if late <= self.soft:
                reported = False
            elif not reported:
                reported = True
                self.report(late, sys._current_frames().get(self._loop_thread))  # pyright: ignore[reportPrivateUsage]

    def report(self, late: float, frame: FrameType | None) -> None:
        found = blamed(frame, self.packages)
        extra: dict[str, object] = {"blocked_seconds": round(late, 2)}
        if found is not None:
            extra |= {"plugin": found[0], "file": found[1], "line": found[2]}
        log.warning("event loop blocked", extra=extra)


def watching(
    soft: float, hard: float, startup: float, packages: Iterable[tuple[str, str]] | None = None
) -> Watchdog:
    """A watchdog for this process's plugins."""
    return Watchdog(soft, hard, startup, dict(packages) if packages is not None else plugin_packages())
