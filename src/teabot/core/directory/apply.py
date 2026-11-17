"""How the directory's writer applies each entry (D55): compare it with the stored row, write the row and its history,
and queue the plugins' events, all in the caller's transaction.

Only the writer calls this, so these are the only writes to members' state. The join-method lookup writes the join
columns alone, and only where the row's `joined_at` still matches.
"""

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from teabot.core.directory.inbox import (
    AuditEntry,
    Banned,
    Entry,
    Joined,
    Left,
    Page,
    RoleDeleted,
    Unbanned,
    Updated,
)
from teabot.core.directory.rows import COLUMNS, MemberRow
from teabot.core.events import Events
from teabot.db.pool import Transaction
from teabot.db.types import Record

# An audit log entry and the event it explains arrive apart, in either order; they match within this window.
MATCH_WINDOW = timedelta(minutes=1)

# Discord's audit log action types about members.
KICK, BAN, UNBAN, MEMBER_UPDATE, ROLE_UPDATE = 20, 22, 23, 24, 25
AUDITED = frozenset({KICK, BAN, UNBAN, MEMBER_UPDATE, ROLE_UPDATE})
# What teabot tells Discord's audit log for a change it makes for a member (`teabot.sdk.authoring`).
TEABOT_REASON = re.compile(r"^via teabot: .*, for member (\d+)$")

ROW = (
    f"SELECT user_id, {COLUMNS}, left_at, observed_at FROM core.members WHERE guild_id = $1 AND user_id = $2"
)
RANGE = f"""
SELECT user_id, {COLUMNS}, left_at, observed_at FROM core.members
WHERE guild_id = $1 AND user_id > $2 AND ($3::bigint IS NULL OR user_id <= $3)
"""
UPSERT = f"""
INSERT INTO core.members (guild_id, user_id, {COLUMNS}, observed_at)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
ON CONFLICT (guild_id, user_id) DO UPDATE SET
    name = EXCLUDED.name, global_name = EXCLUDED.global_name, nickname = EXCLUDED.nickname, bot = EXCLUDED.bot,
    role_ids = EXCLUDED.role_ids, joined_at = EXCLUDED.joined_at, premium_since = EXCLUDED.premium_since,
    timed_out_until = EXCLUDED.timed_out_until, pending = EXCLUDED.pending, flags = EXCLUDED.flags,
    left_at = NULL, observed_at = EXCLUDED.observed_at
"""
# A new join's method is unknown until the lookup finds it.
FORGET_JOIN = """
UPDATE core.members SET join_source = NULL, source_invite_code = NULL, inviter_id = NULL
WHERE guild_id = $1 AND user_id = $2
"""
MARK_LEFT = "UPDATE core.members SET left_at = $3, observed_at = $3 WHERE guild_id = $1 AND user_id = $2"
LEFT_UNSEEN = """
INSERT INTO core.members (guild_id, user_id, name, left_at, observed_at) VALUES ($1, $2, $3, $4, $4)
ON CONFLICT (guild_id, user_id) DO NOTHING
"""
HISTORY = """
INSERT INTO core.member_events (guild_id, user_id, kind, at, since, source, actor_id, reason, detail)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
"""
DROP_ROLE = """
UPDATE core.members SET role_ids = array_remove(role_ids, $2)
WHERE guild_id = $1 AND $2 = ANY(role_ids) RETURNING user_id
"""
# The latest row of a kind for a member, within the window: the one an audit entry or a ban explains.
LATEST = """
SELECT ctid, tableoid FROM core.member_events
WHERE guild_id = $1 AND user_id = $2 AND kind = ANY($3::text[]) AND at >= $4 AND ($5 OR actor_id IS NULL)
ORDER BY at DESC LIMIT 1
"""
EXPLAIN = """
UPDATE core.member_events SET kind = coalesce($3, kind), actor_id = coalesce($4, actor_id),
    reason = coalesce($5, reason)
WHERE ctid = $1 AND tableoid = $2
"""


@dataclass(frozen=True)
class Explanation:
    """What an audit entry or a ban said about a change not yet seen: the kind it makes a `left`, who, and why."""

    kind: str | None
    actor_id: int | None
    reason: str | None
    until: datetime


@dataclass
class Waiting:
    """Explanations waiting for their event, by server, member and the kind of row they explain."""

    entries: dict[tuple[int, int, str], Explanation] = field(
        default_factory=dict[tuple[int, int, str], Explanation]
    )

    def put(self, key: tuple[int, int, str], explanation: Explanation) -> None:
        held = self.entries.get(key)
        # A ban event names no one; the audit entry for the same ban, which may have come first, does.
        if held is not None and held.actor_id is not None and explanation.actor_id is None:
            return
        self.entries[key] = explanation

    def take(self, key: tuple[int, int, str], at: datetime) -> Explanation | None:
        found = self.entries.pop(key, None)
        return found if found is not None and found.until >= at else None

    def expire(self, at: datetime) -> None:
        for key in [k for k, e in self.entries.items() if e.until < at]:
            del self.entries[key]


@dataclass(frozen=True)
class Fact:
    """One row of history: in a server, about a member or, with no `user_id`, the server itself. `since` marks a
    change a reconcile found, which happened between `since` and `at`."""

    guild_id: int
    user_id: int | None
    kind: str
    at: datetime
    detail: Mapping[str, Any] = field(default_factory=dict[str, Any])
    since: datetime | None = None


# When a change was seen, and for one a reconcile found, since when it may have happened.
type When = tuple[datetime, datetime | None]


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def changes(old: MemberRow, new: MemberRow, at: datetime) -> list[tuple[str, dict[str, Any]]]:
    """The history a member's change makes: roles, nickname and timeout. Names are only kept current."""
    found: list[tuple[str, dict[str, Any]]] = []
    added = sorted(set(new.role_ids) - set(old.role_ids))
    removed = sorted(set(old.role_ids) - set(new.role_ids))
    if added or removed:
        found.append(("roles", {"added": [str(r) for r in added], "removed": [str(r) for r in removed]}))
    if old.nickname != new.nickname:
        found.append(("nickname", {"old": old.nickname, "new": new.nickname}))
    if old.timed_out_until != new.timed_out_until:
        if new.timed_out_until is not None and new.timed_out_until > at:
            found.append(("timeout", {"until": _iso(new.timed_out_until)}))
        elif new.timed_out_until is None and old.timed_out_until is not None and old.timed_out_until > at:
            found.append(("timeout", {"until": None}))
    return found


def _roles_payload(user_id: int, detail: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "added": [int(r) for r in detail["added"]],
        "removed": [int(r) for r in detail["removed"]],
    }


class Apply:
    """Applies entries for one shard. `off` holds the servers above the ceiling, whose events reach plugins without
    being stored. `bot_id` is the bot's own user ID, once logged in."""

    def __init__(self, events: Events, off: set[int], bot_id: Callable[[], int | None]) -> None:
        self.events = events
        self.off = off
        self.bot_id = bot_id
        self.waiting = Waiting()

    async def one(self, tx: Transaction, entry: Entry) -> None:
        match entry:
            case Joined():
                await self._joined(tx, entry)
            case Updated():
                await self._updated(tx, entry)
            case Left():
                await self._left(tx, entry)
            case Banned():
                await self._banned(tx, entry)
            case Unbanned():
                await self._unbanned(tx, entry)
            case RoleDeleted():
                await self._role_deleted(tx, entry)
            case AuditEntry():
                await self._audit(tx, entry)
            case Page():
                await self._page(tx, entry)

    async def _fire(
        self,
        tx: Transaction,
        guild_id: int,
        event: Any,
        payload: dict[str, Any],
        since: datetime | None = None,
    ) -> None:
        await self.events.fire(guild_id, event, payload, within=tx, since=since)

    async def _history(self, tx: Transaction, fact: Fact) -> None:
        """Write one row of history, with what a waiting audit entry or ban says about it."""
        kind, user_id = fact.kind, fact.user_id
        explained = (
            self.waiting.take((fact.guild_id, user_id, kind), fact.at) if user_id is not None else None
        )
        if explained is not None and explained.kind is not None:
            kind = explained.kind
        await tx.execute(
            HISTORY,
            fact.guild_id,
            user_id,
            kind,
            fact.at,
            fact.since,
            "event" if fact.since is None else "reconcile",
            explained.actor_id if explained else None,
            explained.reason if explained else None,
            json.dumps(dict(fact.detail)),
        )

    async def _row(self, tx: Transaction, guild_id: int, user_id: int) -> Record | None:
        return await tx.fetchrow(ROW + " FOR UPDATE", guild_id, user_id)

    async def _store(self, tx: Transaction, guild_id: int, member: MemberRow, observed: datetime) -> None:
        await tx.execute(UPSERT, guild_id, member.user_id, *member.values(), observed)

    async def _joined(self, tx: Transaction, entry: Joined) -> None:
        guild_id, member = entry.guild_id, entry.member
        payload = {"user_id": member.user_id}
        if guild_id in self.off:
            await self._fire(tx, guild_id, "member_join", payload)
            return
        row = await self._row(tx, guild_id, member.user_id)
        if row is not None and row["left_at"] is None:
            if row["joined_at"] == member.joined_at:
                # The same join again: discord.py's cache can make Discord's event arrive twice.
                await self._store(tx, guild_id, member, entry.at)
                return
            # A leave the bot never heard, as when it was down: recorded as the reconcile would have.
            await self._history(
                tx, Fact(guild_id, member.user_id, "left", entry.at, since=row["observed_at"])
            )
        await self._store(tx, guild_id, member, entry.at)
        await tx.execute(FORGET_JOIN, guild_id, member.user_id)
        await self._history(tx, Fact(guild_id, member.user_id, "joined", entry.at))
        await self._fire(tx, guild_id, "member_join", payload)

    async def _updated(self, tx: Transaction, entry: Updated) -> None:
        guild_id, member = entry.guild_id, entry.member
        if guild_id in self.off:
            await self._cached_roles(tx, entry, store=False)
            return
        row = await self._row(tx, guild_id, member.user_id)
        if row is None:
            await self._store(tx, guild_id, member, entry.at)
            await self._cached_roles(tx, entry, store=True)
            return
        if row["left_at"] is not None:
            # Back without a join the bot heard.
            await self._store(tx, guild_id, member, entry.at)
            await tx.execute(FORGET_JOIN, guild_id, member.user_id)
            await self._history(tx, Fact(guild_id, member.user_id, "joined", entry.at, since=row["left_at"]))
            await self._fire(tx, guild_id, "member_join", {"user_id": member.user_id}, row["left_at"])
            return
        await self._store(tx, guild_id, member, entry.at)
        await self._changed(tx, guild_id, (MemberRow.from_record(row), member), (entry.at, None))

    async def _cached_roles(self, tx: Transaction, entry: Updated, *, store: bool) -> None:
        """A change for a member with no row: discord.py's cached copy, when it had one, says what changed."""
        if entry.cached_roles is None:
            return
        added = sorted(set(entry.member.role_ids) - set(entry.cached_roles))
        removed = sorted(set(entry.cached_roles) - set(entry.member.role_ids))
        if not (added or removed):
            return
        detail = {"added": [str(r) for r in added], "removed": [str(r) for r in removed]}
        if store:
            await self._history(tx, Fact(entry.guild_id, entry.member.user_id, "roles", entry.at, detail))
        await self._fire(tx, entry.guild_id, "member_roles", _roles_payload(entry.member.user_id, detail))

    async def _changed(
        self, tx: Transaction, guild_id: int, rows: tuple[MemberRow, MemberRow], when: When
    ) -> None:
        """Record what changed between the stored row and the new one, and tell plugins of role changes."""
        old, new = rows
        at, since = when
        for kind, detail in changes(old, new, at):
            await self._history(tx, Fact(guild_id, new.user_id, kind, at, detail, since))
            if kind == "roles":
                await self._fire(tx, guild_id, "member_roles", _roles_payload(new.user_id, detail), since)

    async def _left(self, tx: Transaction, entry: Left) -> None:
        guild_id, user_id = entry.guild_id, entry.user_id
        payload = {"user_id": user_id, "name": entry.name}
        if guild_id in self.off:
            await self._fire(tx, guild_id, "member_leave", payload)
            return
        row = await self._row(tx, guild_id, user_id)
        if row is not None and row["left_at"] is not None:
            return
        if row is None:
            await tx.execute(LEFT_UNSEEN, guild_id, user_id, entry.name, entry.at)
        else:
            await tx.execute(MARK_LEFT, guild_id, user_id, entry.at)
        await self._history(tx, Fact(guild_id, user_id, "left", entry.at))
        await self._fire(tx, guild_id, "member_leave", payload)

    async def _explain(
        self,
        tx: Transaction,
        key: tuple[int, int, str],
        kinds: list[str],
        explanation: Explanation,
        at: datetime,
    ) -> bool:
        """Explain the member's latest row of `kinds` within the window, or hold the explanation for its event.
        Returns whether a row was found."""
        guild_id, user_id, _kind = key
        found = await tx.fetchrow(
            LATEST, guild_id, user_id, kinds, at - MATCH_WINDOW, explanation.actor_id is None
        )
        if found is None:
            self.waiting.put(key, explanation)
            return False
        await tx.execute(
            EXPLAIN,
            found["ctid"],
            found["tableoid"],
            explanation.kind,
            explanation.actor_id,
            explanation.reason,
        )
        return True

    async def _banned(self, tx: Transaction, entry: Banned) -> None:
        if entry.guild_id in self.off:
            return
        row = await tx.fetchrow(ROW, entry.guild_id, entry.user_id)
        if row is None:
            return
        explanation = Explanation("banned", None, None, entry.at + MATCH_WINDOW)
        key = (entry.guild_id, entry.user_id, "left")
        if await self._explain(tx, key, ["left", "kicked", "banned"], explanation, entry.at):
            return
        if row["left_at"] is not None:
            # Banned after leaving: its own row, which nothing else will make.
            self.waiting.take(key, entry.at)
            await self._history(tx, Fact(entry.guild_id, entry.user_id, "banned", entry.at))

    async def _unbanned(self, tx: Transaction, entry: Unbanned) -> None:
        if entry.guild_id in self.off or await tx.fetchrow(ROW, entry.guild_id, entry.user_id) is None:
            return
        await self._history(tx, Fact(entry.guild_id, entry.user_id, "unbanned", entry.at))

    async def _role_deleted(self, tx: Transaction, entry: RoleDeleted) -> None:
        if entry.guild_id in self.off:
            return
        holders = [r["user_id"] for r in await tx.fetch(DROP_ROLE, entry.guild_id, entry.role_id)]
        detail = {"role_id": str(entry.role_id), "name": entry.name, "holders": [str(h) for h in holders]}
        await self._history(tx, Fact(entry.guild_id, None, "role_deleted", entry.at, detail))

    def _actor(self, entry: AuditEntry) -> int | None:
        """Who made a change: for one teabot made for a member, that member, whom its reason names."""
        ours = entry.actor_id is not None and entry.actor_id == self.bot_id()
        if ours and (found := TEABOT_REASON.match(entry.reason or "")):
            return int(found.group(1))
        return entry.actor_id

    async def _audit(self, tx: Transaction, entry: AuditEntry) -> None:
        if entry.guild_id in self.off or entry.action not in AUDITED:
            return
        until = entry.at + MATCH_WINDOW
        actor, reason = self._actor(entry), entry.reason
        user = (entry.guild_id, entry.target_id)
        if entry.action in (KICK, BAN):
            kind = "kicked" if entry.action == KICK else "banned"
            kinds = ["left"] if entry.action == KICK else ["left", "banned"]
            await self._explain(tx, (*user, "left"), kinds, Explanation(kind, actor, reason, until), entry.at)
            return
        if entry.action == UNBAN:
            await self._explain(
                tx, (*user, "unbanned"), ["unbanned"], Explanation(None, actor, reason, until), entry.at
            )
            return
        keys = {c.get("key") for c in entry.changes}
        kinds: list[str] = []
        if entry.action == ROLE_UPDATE:
            kinds = ["roles"]
        else:
            kinds = [
                kind
                for key, kind in (("nick", "nickname"), ("communication_disabled_until", "timeout"))
                if key in keys
            ]
        for kind in kinds:
            reason_here = reason if kind == "timeout" else None
            await self._explain(
                tx, (*user, kind), [kind], Explanation(None, actor, reason_here, until), entry.at
            )

    async def _page(self, tx: Transaction, page: Page) -> None:
        """Compare one page of Discord's member list with the stored rows in its range of IDs."""
        if page.guild_id in self.off:
            return
        stored = {
            r["user_id"]: r
            for r in await tx.fetch(RANGE + " FOR UPDATE", page.guild_id, page.after, page.through)
        }
        observed = page.older_than + MATCH_WINDOW
        since = None if page.backfill else page.since
        for member in page.members:
            row = stored.pop(member.user_id, None)
            if row is not None and row["observed_at"] > page.older_than:
                continue
            await self._store(tx, page.guild_id, member, observed)
            if page.backfill:
                continue
            await self._compared(tx, page, member, row)
        if not page.mark_left:
            return
        for user_id, row in stored.items():
            if row["left_at"] is None and row["observed_at"] <= page.older_than:
                await tx.execute(MARK_LEFT, page.guild_id, user_id, observed)
                if since is not None:
                    await self._history(tx, Fact(page.guild_id, user_id, "left", observed, since=since))
                    payload = {"user_id": user_id, "name": row["name"]}
                    await self._fire(tx, page.guild_id, "member_leave", payload, since)

    async def _compared(self, tx: Transaction, page: Page, member: MemberRow, row: Record | None) -> None:
        """Record what one listed member's row says changed while the bot was not watching."""
        guild_id, since, observed = page.guild_id, page.since, page.older_than + MATCH_WINDOW
        payload = {"user_id": member.user_id}
        if row is None or row["left_at"] is not None or row["joined_at"] != member.joined_at:
            if row is not None and row["left_at"] is None:
                await self._history(tx, Fact(guild_id, member.user_id, "left", observed, since=since))
            await tx.execute(FORGET_JOIN, guild_id, member.user_id)
            await self._history(tx, Fact(guild_id, member.user_id, "joined", observed, since=since))
            await self._fire(tx, guild_id, "member_join", payload, since)
            return
        await self._changed(tx, guild_id, (MemberRow.from_record(row), member), (observed, since))
