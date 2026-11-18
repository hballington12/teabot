"""Member labels: the core's side of `ctx.labels` and of filters on labels.

A plugin replaces its whole set for a server at once. The write compares with what is stored, inside one
transaction, and touches only the rows that changed, so a large server's hourly replace stays cheap. A plugin's
labels count in filters only while it is enabled in the server and its data is within its freshness window, so
a plugin that stops syncing stops counting. When labels change, or become fresh again, `labels_changed` fires.
"""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta

from teabot.core.directory import state as states
from teabot.db.pool import Database, Queries
from teabot.sdk.labels import DEFAULT_FRESH, checked
from teabot.sdk.members import DirectoryUnavailable

type Notify = Callable[[int, str, Queries], Awaitable[None]]

STATE = "SELECT as_of FROM core.label_state WHERE guild_id = $1 AND plugin_id = $2"
LOCK = "SELECT pg_advisory_xact_lock(hashtextextended('labels:' || $1::bigint::text || ':' || $2::text, 0))"
STORED = "SELECT user_id, labels FROM core.member_labels WHERE guild_id = $1 AND plugin_id = $2"
DROP = "DELETE FROM core.member_labels WHERE guild_id = $1 AND plugin_id = $2 AND user_id = ANY($3::bigint[])"
UPSERT = """
INSERT INTO core.member_labels (guild_id, plugin_id, user_id, labels) VALUES ($1, $2, $3, $4)
ON CONFLICT (guild_id, plugin_id, user_id) DO UPDATE SET labels = EXCLUDED.labels
"""
SAVE_STATE = """
INSERT INTO core.label_state (guild_id, plugin_id, as_of, written_at) VALUES ($1, $2, $3, $4)
ON CONFLICT (guild_id, plugin_id) DO UPDATE SET as_of = EXCLUDED.as_of, written_at = EXCLUDED.written_at
"""
ENABLED = "SELECT enabled FROM core.guild_plugins WHERE guild_id = $1 AND plugin_id = $2"
# A plugin's clock may run a little ahead; data from the future counts as now.
AHEAD = timedelta(minutes=5)


class LabelService:
    """Every plugin's labels. `fresh_for` is each loaded plugin's freshness window, from its manifest; `notify`
    fires `labels_changed` for a server inside the write's transaction."""

    def __init__(
        self, db: Database, fresh_for: Mapping[str, timedelta], notify: Notify | None = None
    ) -> None:
        self.db = db
        self.fresh_for = dict(fresh_for)
        self.notify = notify

    def bound(self, plugin_id: str, guild_id: int) -> "GuildLabels":
        return GuildLabels(self, plugin_id, guild_id)

    def window(self, plugin_id: str) -> timedelta:
        return self.fresh_for.get(plugin_id, DEFAULT_FRESH)

    async def live(self, guild_id: int, plugin_id: str, now: datetime | None = None) -> bool:
        """Whether `plugin_id`'s labels count in this server now: the plugin is loaded and enabled here, and its
        data is within its window."""
        if plugin_id not in self.fresh_for:
            return False
        if not await self.db.fetchval(ENABLED, guild_id, plugin_id):
            return False
        as_of = await self.db.fetchval(STATE, guild_id, plugin_id)
        return _fresh(as_of, self.window(plugin_id), now or datetime.now(UTC))

    async def replace_all(
        self, plugin_id: str, guild_id: int, labels: Mapping[int, Iterable[str]], as_of: datetime
    ) -> int:
        wanted = {int(user_id): checked(values) for user_id, values in labels.items()}
        wanted = {user_id: values for user_id, values in wanted.items() if values}
        state = await states.load(self.db, guild_id)
        if state.off or not state.backfilled:
            raise DirectoryUnavailable(
                "The member directory is not ready in this server, so labels can't be written."
            )
        now = datetime.now(UTC)
        as_of = min(as_of if as_of.tzinfo else as_of.replace(tzinfo=UTC), now + AHEAD)
        window = self.window(plugin_id)
        async with self.db.transaction() as tx:
            await tx.execute(LOCK, guild_id, plugin_id)
            was_fresh = _fresh(await tx.fetchval(STATE, guild_id, plugin_id), window, now)
            stored = {r["user_id"]: tuple(r["labels"]) for r in await tx.fetch(STORED, guild_id, plugin_id)}
            gone = [user_id for user_id in stored if user_id not in wanted]
            changed = [(u, v) for u, v in wanted.items() if stored.get(u) != v]
            if gone:
                await tx.execute(DROP, guild_id, plugin_id, gone)
            for user_id, values in changed:
                await tx.execute(UPSERT, guild_id, plugin_id, user_id, list(values))
            await tx.execute(SAVE_STATE, guild_id, plugin_id, as_of, now)
            moved = len(gone) + len(changed)
            if self.notify is not None and (moved or (not was_fresh and _fresh(as_of, window, now))):
                await self.notify(guild_id, plugin_id, tx)
        return moved


class GuildLabels:
    """One plugin's labels in one server, as `ctx.labels`."""

    def __init__(self, service: LabelService, plugin_id: str, guild_id: int) -> None:
        self.service = service
        self.plugin_id = plugin_id
        self.guild_id = guild_id

    async def replace_all(self, labels: Mapping[int, Iterable[str]], /, *, as_of: datetime) -> int:
        return await self.service.replace_all(self.plugin_id, self.guild_id, labels, as_of)


def _fresh(as_of: datetime | None, window: timedelta, now: datetime) -> bool:
    return as_of is not None and as_of > now - window
