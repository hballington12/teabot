"""Discord events for plugins (D6): a member joining or leaving queues a job for each plugin that listens.

Each event becomes one of the plugin's jobs, `on_<event>`, so a failing handler is retried as any job is, never
stops another plugin's, and shows in `/admin job_status`. Only plugins enabled in the event's server hear it.
"""

from collections.abc import Mapping, Set

from teabot.core.queue import NewJob, Queue
from teabot.db.pool import Database
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

    def __init__(self, db: Database, queue: Queue, listeners: Mapping[str, Set[EventName]]) -> None:
        self.db = db
        self.queue = queue
        self.listeners = listeners

    async def fire(self, guild_id: int, event: EventName, user_id: int) -> int:
        """Queue `event` for every listening plugin enabled in the server; returns how many."""
        wanted = [plugin_id for plugin_id, events in self.listeners.items() if event in events]
        if not wanted:
            return 0
        rows = await self.db.fetch(ENABLED_HERE, guild_id, wanted)
        for row in rows:
            job = NewJob(
                row["plugin_id"],
                event_job(event),
                guild_id,
                payload={"user_id": user_id},
                max_attempts=EVENT_ATTEMPTS,
            )
            await self.queue.schedule(job)
        return len(rows)
