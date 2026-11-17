"""Each server's directory state (D55): how far its copy can be trusted, which every answer carries."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, Field

from teabot.db.pool import Queries

LOAD = """
SELECT history_from, backfilled, reconciled_at, dropped, guard_stopped, off, joins_read_to
FROM core.directory_state WHERE guild_id = $1
"""
ENSURE = "INSERT INTO core.directory_state (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING"
RECONCILED = """
UPDATE core.directory_state SET reconciled_at = $2, backfilled = backfilled OR $3, guard_stopped = NOT $3,
    history_from = CASE WHEN $3 THEN coalesce(history_from, $2) ELSE history_from END, dropped = false
WHERE guild_id = $1
"""
SET_OFF = "UPDATE core.directory_state SET off = $2, backfilled = backfilled AND NOT $2 WHERE guild_id = $1"
MARK_DROPPED = "UPDATE core.directory_state SET dropped = true WHERE guild_id = ANY($1::bigint[])"
JOINS_READ = "UPDATE core.directory_state SET joins_read_to = $2 WHERE guild_id = $1"


@dataclass(frozen=True)
class State:
    history_from: datetime | None = None
    backfilled: bool = False
    reconciled_at: datetime | None = None
    dropped: bool = False
    guard_stopped: bool = False
    off: bool = False
    joins_read_to: datetime | None = None


async def load(db: Queries, guild_id: int) -> State:
    row = await db.fetchrow(LOAD, guild_id)
    return State() if row is None else State(**dict(row))


class DirectoryStatus(BaseModel):
    """How far an answer from the member directory can be trusted."""

    ready: bool = Field(
        description="Whether the directory holds every member: its first copy is done and it is on"
    )
    off: bool = Field(
        description="Whether the directory is off in this server, above the instance's member limit"
    )
    history_from: datetime | None = Field(
        description="When history starts: joins, leaves and role changes before it are unknown"
    )
    reconciled_at: datetime | None = Field(
        description="When the directory was last compared with Discord's list"
    )
    behind: bool = Field(
        description="Whether events were missed since then, or the last comparison stopped short, so it may lag"
    )

    @classmethod
    def of(cls, state: State) -> "DirectoryStatus":
        return cls(
            ready=state.backfilled and not state.off,
            off=state.off,
            history_from=state.history_from,
            reconciled_at=state.reconciled_at,
            behind=state.dropped or state.guard_stopped,
        )
