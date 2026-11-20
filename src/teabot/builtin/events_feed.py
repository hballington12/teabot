"""`admin.events`, the events feed (events-and-tickets.md): a server's plugin events after a cursor, so a program on
the service API or MCP hears what a subscribing plugin hears.

Events are news, and state lives at the source: rows go after 30 days, so a program reconciles through the source's
read actions too. The feed never skips an event. It orders events by the transaction that wrote them, then by ID,
and returns only rows whose transaction is older than every transaction still open, so nothing can later appear
before the cursor. A long write transaction holds the feed back until it ends: late, never wrong. It isn't commit
order either, so a program orders by `id` per thing, as a plugin subscriber does.

Member-written text, at the paths recorded when the event was emitted, comes back as `{"untrusted_text": ...}`, as
MCP marks it in every output (D23).
"""

import json
import re
from datetime import datetime
from typing import Annotated, Any, cast

import discord
from pydantic import BaseModel, Field

from teabot.db.pool import Database
from teabot.sdk import ActionContext, ActionError, ActionSpec, Risk, Surface

MANAGE_SERVER = discord.Permissions(manage_guild=True)
LIMIT = 100
FEED = """
SELECT id, tx_id::text AS tx_id, source, name, payload, by, at, untrusted FROM core.events
WHERE guild_id = $1 AND tx_id < pg_snapshot_xmin(pg_current_snapshot())
  AND (tx_id, id) > ($2::text::xid8, $3::bigint)
  AND (cardinality($4::text[]) = 0 OR source || '.' || name = ANY($4::text[]))
ORDER BY tx_id, id LIMIT $5
"""
CURSOR = re.compile(r"^(\d+)\.(\d+)$")

type EventName = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")]


class EventsQuery(BaseModel):
    after: str = Field(
        default="", max_length=60, description="The cursor the last page gave, or empty to start"
    )
    names: list[EventName] = Field(
        default=[], max_length=10, description="Only these events, such as tickets.accepted; all when empty"
    )
    limit: int = Field(default=LIMIT, ge=1, le=LIMIT, description="How many events, up to 100")


class FeedEvent(BaseModel):
    id: int
    source: str
    name: str
    at: datetime
    by: str | None = Field(description="The member who caused it, none for the system, 0 once deleted")
    data: dict[str, Any]


class EventsPage(BaseModel):
    events: list[FeedEvent]
    cursor: str = Field(description="Pass as after for the next page")

    def render(self) -> str:
        if not self.events:
            return "No new events."
        lines = [f"{e.id} {e.source}.{e.name} at {e.at:%Y-%m-%d %H:%M}" for e in self.events]
        return "\n".join([*lines, f"Next: after:{self.cursor}"])


def _marked(data: Any, parts: list[str]) -> Any:
    """`data` with the value at the path `parts` wrapped as untrusted."""
    if not parts:
        return None if data is None else {"untrusted_text": data}
    head, rest = parts[0], parts[1:]
    if head == "[]":
        return [_marked(v, rest) for v in cast(list[Any], data)] if isinstance(data, list) else data
    if isinstance(data, dict):
        found = cast(dict[str, Any], data)
        if head in found:
            return {**found, head: _marked(found[head], rest)}
    return cast(Any, data)


def mark_untrusted(data: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    """The payload with member-written text at each recorded path wrapped, such as `items[].note`."""
    out: Any = data
    for path in paths:
        out = _marked(out, re.findall(r"[^.\[\]]+|\[\]", path))
    return cast(dict[str, Any], out)


def _json(value: Any) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(value) if isinstance(value, str) else value)


class EventsFeed:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def events(self, ctx: ActionContext, data: EventsQuery) -> EventsPage:
        tx_id, last = "0", 0
        if data.after:
            found = CURSOR.fullmatch(data.after)
            if found is None:
                raise ActionError("That cursor isn't one the feed gave. Start again with an empty after.")
            tx_id, last = found.group(1), int(found.group(2))
        rows = await self.db.fetch(FEED, ctx.guild.id, tx_id, last, list(data.names), data.limit)
        events = [
            FeedEvent(
                id=r["id"],
                source=r["source"],
                name=r["name"],
                at=r["at"],
                by=None if r["by"] is None else str(r["by"]),
                data=mark_untrusted(_json(r["payload"]), list(r["untrusted"])),
            )
            for r in rows
        ]
        cursor = f"{rows[-1]['tx_id']}.{rows[-1]['id']}" if rows else data.after
        return EventsPage(events=events, cursor=cursor)

    def specs(self) -> dict[str, ActionSpec[Any, Any]]:
        return {
            "admin.events": ActionSpec(
                "admin.events",
                "Plugin events here after a cursor, for a program following the server",
                EventsQuery,
                EventsPage,
                Risk.READ,
                self.events,
                default_permissions=MANAGE_SERVER,
                surfaces=Surface.MCP | Surface.SERVICE,
            )
        }
