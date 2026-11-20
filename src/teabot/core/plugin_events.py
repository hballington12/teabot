"""Delivering plugin events (events-and-tickets.md): from a transaction's events to one job per subscriber.

A plugin's `emit_event` writes the event and queues one `deliver_events` job for its transaction. That job queues
one `on_event:<name>` job per plugin that subscribes and is enabled in the server, for each event, from the handlers
of the plugins this process loaded. A subscriber's job carries the event's ID only: when it runs, the core loads the
event, skips it if it is gone, and hands the plugin's handler the event. A job that runs out of attempts tells the
server's log channel, so a lost event is seen.
"""

import json
import logging
from collections.abc import Awaitable, Callable, Mapping, Set
from typing import Any

from teabot.core.audit import AuditLog
from teabot.core.loader import SUBSCRIBER_PREFIX, event_job_name
from teabot.core.queue import JobContext, NewJob, Queue
from teabot.db.pool import Database
from teabot.sdk.events import SUBSCRIBER_ATTEMPTS

log = logging.getLogger(__name__)

DELIVER_HANDLER = "deliver_events"
EVENTS_OF_TX = """
SELECT id, source || '.' || name AS full_name FROM core.events
WHERE guild_id = $1 AND tx_id = $2::text::xid8 ORDER BY id
"""
ENABLED_HERE = """
SELECT plugin_id FROM core.guild_plugins WHERE guild_id = $1 AND enabled AND plugin_id = ANY($2::text[])
"""
ONE_EVENT = "SELECT id, source, name, payload, by, at FROM core.events WHERE id = $1 AND guild_id = $2"


class Deliver:
    """The `deliver_events` handler: queue each of a transaction's events for its subscribers."""

    def __init__(self, db: Database, queue: Queue, subscribers: Mapping[str, Set[str]]) -> None:
        self.db = db
        self.queue = queue
        self.subscribers = {p: frozenset(names) for p, names in subscribers.items() if names}

    async def __call__(self, ctx: JobContext) -> None:
        guild_id = ctx.job.guild_id
        if guild_id is None:
            return
        async with self.db.transaction() as tx:
            events = await tx.fetch(EVENTS_OF_TX, guild_id, str(ctx.job.payload["tx_id"]))
            names = {str(e["full_name"]) for e in events}
            wanted = [p for p, subs in self.subscribers.items() if subs & names]
            if not wanted:
                return
            enabled = [str(r["plugin_id"]) for r in await tx.fetch(ENABLED_HERE, guild_id, wanted)]
            for event in events:
                for plugin_id in enabled:
                    if event["full_name"] in self.subscribers[plugin_id]:
                        job = NewJob(
                            plugin_id,
                            event_job_name(str(event["full_name"])),
                            guild_id,
                            payload={"event_id": int(event["id"])},
                            max_attempts=SUBSCRIBER_ATTEMPTS,
                        )
                        await self.queue.schedule(job, within=tx)


def is_subscriber_job(handler: str) -> bool:
    return handler.startswith(SUBSCRIBER_PREFIX)


type Run = Callable[[JobContext, Mapping[str, Any]], Awaitable[None]]


def receiving(db: Database, audit: AuditLog | None, run: Run) -> Callable[[JobContext], Awaitable[None]]:
    """A subscriber's job: load its event, skip one that is gone, run the handler with the event as its payload,
    and tell the log channel when the last attempt fails."""

    async def handle(ctx: JobContext) -> None:
        guild_id = ctx.job.guild_id
        row = await db.fetchrow(ONE_EVENT, int(ctx.job.payload["event_id"]), guild_id)
        if row is None or guild_id is None:
            log.info("event gone before its subscriber ran", extra={"job_id": ctx.job.id})
            return
        event = {
            "id": int(row["id"]),
            "source": str(row["source"]),
            "name": str(row["name"]),
            "data": json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"],
            "by": row["by"],
            "at": row["at"].isoformat(),
        }
        try:
            await run(ctx, {"event": event})
        except Exception as exc:
            if audit is not None and ctx.job.attempt >= ctx.job.max_attempts:
                details = {
                    "event": f"{event['source']}.{event['name']}",
                    "event_id": event["id"],
                    "plugin": ctx.job.plugin_id,
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                }
                async with db.transaction() as tx:
                    await audit.system_change(tx, guild_id, "events.lost", details, failed=True)
            raise

    return handle
