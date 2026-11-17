"""Discord events for plugins (D6): a member joining or leaving, a message, a reaction, a member's roles changing
or a move between voice channels queues a job for each plugin that listens.

Each event becomes one of the plugin's jobs, `on_<event>`, so a failing handler is retried as any job is, never
stops another plugin's, and shows in `/admin job_status`. Only plugins enabled in the event's server hear it.

A change the member directory's reconcile found, which happened while the bot was not watching, is a late event, with
the time the gap began (D55). Only plugins whose handler asked for late events hear it.
"""

from collections.abc import Mapping, Set
from datetime import datetime
from typing import Any

from teabot.core.queue import NewJob, Queue
from teabot.db.pool import Database, Queries
from teabot.sdk.plugin import EventName

ENABLED_HERE = """
SELECT plugin_id FROM core.guild_plugins WHERE guild_id = $1 AND enabled AND plugin_id = ANY($2::text[])
"""
# An event that keeps failing is not worth a retry an hour later; it is about the moment it happened.
EVENT_ATTEMPTS = 3


def event_job(event: EventName) -> str:
    """The job a plugin's handler for `event` runs as."""
    return f"on_{event}"


class Events:
    """Queues each event for the plugins that listen for it and are enabled where it happened."""

    def __init__(
        self,
        db: Database,
        queue: Queue,
        listeners: Mapping[str, Set[EventName]],
        late: Mapping[str, Set[EventName]] | None = None,
    ) -> None:
        self.db = db
        self.queue = queue
        self.listeners = listeners
        self.late = late or {}

    def hears(self, event: EventName) -> bool:
        """Whether any loaded plugin listens for `event`, so the gateway can skip the rest without a query."""
        return any(event in events for events in self.listeners.values())

    async def enabled(self, guild_id: int, plugin_id: str, user_id: int) -> None:
        """A server has just turned `plugin_id` on: queue its enable handler, if it has one."""
        if "enable" in self.listeners.get(plugin_id, ()):
            job = NewJob(plugin_id, event_job("enable"), guild_id, payload={"user_id": user_id})
            await self.queue.schedule(job)

    async def fire(
        self,
        guild_id: int,
        event: EventName,
        payload: Mapping[str, Any],
        *,
        within: Queries | None = None,
        since: datetime | None = None,
    ) -> int:
        """Queue `event` for every listening plugin enabled in the server; returns how many. `payload` is what
        the handler receives, such as `user_id`, and for a leave the member's username as `name`, which the
        handler can no longer look up. `within` queues the jobs in an open transaction. `since` makes it a late
        event, for the plugins that asked for them."""
        if since is None:
            wanted = [plugin_id for plugin_id, events in self.listeners.items() if event in events]
        else:
            wanted = [plugin_id for plugin_id, events in self.late.items() if event in events]
        if not wanted:
            return 0
        queries = within or self.db
        rows = await queries.fetch(ENABLED_HERE, guild_id, wanted)
        body = dict(payload) if since is None else {**payload, "since": since.isoformat()}
        for row in rows:
            job = NewJob(
                row["plugin_id"], event_job(event), guild_id, payload=body, max_attempts=EVENT_ATTEMPTS
            )
            await self.queue.schedule(job, within=within)
        return len(rows)
