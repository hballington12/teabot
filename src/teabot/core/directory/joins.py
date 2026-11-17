"""How each member joined (D55, S9): Discord's member search, which is not in its published docs and is used for
this alone. It is read newest join first, back to the newest join read before. A failure, or the search being off,
leaves join method unknown, and nothing else is affected.

Its results are written to the join columns only where the row's `joined_at` still matches, so a lookup racing a
rejoin never gives the new join the old one's method.
"""

import logging
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol, cast

from teabot.core.directory.rows import timestamp
from teabot.db.pool import Database

log = logging.getLogger(__name__)

PAGE = 1000
NEWEST_FIRST = 1
MEMBERS = """
UPDATE core.members m SET join_source = v.source, source_invite_code = v.code, inviter_id = v.inviter
FROM unnest($2::bigint[], $3::timestamptz[], $4::integer[], $5::text[], $6::bigint[])
    AS v(user_id, joined_at, source, code, inviter)
WHERE m.guild_id = $1 AND m.user_id = v.user_id AND m.joined_at = v.joined_at
"""
JOIN_EVENTS = """
UPDATE core.member_events e SET detail = e.detail || jsonb_build_object(
    'join_source', v.source, 'source_invite_code', v.code, 'inviter_id', v.inviter::text)
FROM unnest($2::bigint[], $3::timestamptz[], $4::integer[], $5::text[], $6::bigint[])
    AS v(user_id, joined_at, source, code, inviter)
WHERE e.guild_id = $1 AND e.user_id = v.user_id AND e.kind = 'joined' AND e.at >= v.joined_at - interval '1 minute'
"""


class Search(Protocol):
    async def search_members(self, guild_id: int, body: Mapping[str, Any], /) -> Any: ...


def _ms(when: datetime) -> int:
    return int(when.timestamp() * 1000)


type Found = tuple[int, datetime, int | None, str | None, int | None]


def _members(found: Any) -> list[Mapping[str, Any]] | None:
    """The results of one search, or None when Discord sent none."""
    if not isinstance(found, dict):
        return None
    members: Any = cast(dict[str, Any], found).get("members")
    return cast(list[Mapping[str, Any]], members) if isinstance(members, list) else None


def _entry(entry: Mapping[str, Any]) -> Found | None:
    """One search result: the member, when they joined, and how."""
    member: Mapping[str, Any] = entry["member"]
    joined = timestamp(member.get("joined_at"))
    if joined is None:
        return None
    inviter = entry.get("inviter_id")
    return (
        int(member["user"]["id"]),
        joined,
        entry.get("join_source_type"),
        entry.get("source_invite_code"),
        int(inviter) if inviter is not None else None,
    )


async def read_joins(
    search: Search, db: Database, guild_id: int, read_to: datetime | None
) -> datetime | None:
    """Read join methods newer than `read_to`, all of them when it is None. Returns the newest join read, for the next
    lookup to stop at."""
    body: dict[str, Any] = {"limit": PAGE, "sort": NEWEST_FIRST}
    newest: datetime | None = None
    while True:
        entries = _members(await search.search_members(guild_id, body))
        if entries is None:
            # Discord answers 202 while it builds a server's search index; the next lookup tries again.
            log.info("member search not ready", extra={"guild_id": guild_id})
            return newest or read_to
        rows: list[Found] = []
        for entry in entries:
            row = _entry(entry)
            if row is None:
                continue
            if read_to is not None and row[1] <= read_to:
                await _write(db, guild_id, rows)
                return newest or read_to
            newest = newest or row[1]
            rows.append(row)
        await _write(db, guild_id, rows)
        if len(entries) < PAGE or not rows:
            return newest or read_to
        body["after"] = {"guild_joined_at": _ms(rows[-1][1]), "user_id": str(rows[-1][0])}


async def _write(
    db: Database, guild_id: int, rows: list[tuple[int, datetime, int | None, str | None, int | None]]
) -> None:
    if not rows:
        return
    columns = [list(c) for c in zip(*rows, strict=True)]
    async with db.transaction() as tx:
        await tx.execute(MEMBERS, guild_id, *columns)
        await tx.execute(JOIN_EVENTS, guild_id, *columns)
