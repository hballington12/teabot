"""The health report behind `/healthz` (D36, D40). Healthy means every shard is connected and the database answers."""

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg

from teabot.db.pool import Database

STATM = Path("/proc/self/statm")
BACKLOG = "SELECT count(*) FROM core.jobs WHERE state = 'pending' AND run_at <= now()"

type ShardLatencies = Callable[[], dict[int, float | None]]
type PluginStatuses = Callable[[], dict[str, str]]


def memory_mb(statm: Path = STATM) -> float | None:
    """The process's resident memory now, in megabytes, or None where the system does not say, as on macOS and
    Windows. The current figure shows a leak growing; a peak would only ever rise."""
    try:
        resident_pages = int(statm.read_text().split()[1])
    except (OSError, IndexError, ValueError):
        return None
    return round(resident_pages * os.sysconf("SC_PAGE_SIZE") / 2**20, 1)


@dataclass(frozen=True)
class HealthReport:
    ok: bool
    body: dict[str, Any]


class Health:
    """Gathers the report. Shard latency is None for a shard that is not connected."""

    def __init__(self, version: str, db: Database, shards: ShardLatencies, plugins: PluginStatuses) -> None:
        self.version = version
        self.db = db
        self.shards = shards
        self.plugins = plugins

    async def _backlog(self) -> int | None:
        try:
            backlog: int = await self.db.fetchval(BACKLOG)
        except (asyncpg.PostgresError, asyncpg.InterfaceError, OSError):
            return None
        return backlog

    async def check(self) -> HealthReport:
        shards = self.shards()
        backlog = await self._backlog()
        database = backlog is not None
        ok = database and bool(shards) and all(latency is not None for latency in shards.values())
        body: dict[str, Any] = {
            "ok": ok,
            "version": self.version,
            "shards": {str(shard): latency for shard, latency in shards.items()},
            "database": database,
            "queue_backlog": backlog,
            "memory_mb": memory_mb(),
            "plugins": self.plugins(),
        }
        return HealthReport(ok, body)
