"""The directory's way in from the gateway (D55): discord.py's parsers for member events, wrapped.

discord.py drops some member events before any handler sees them: an update for a member it has not cached, a join
for one it has, and a deletion of a role it has not cached. Its parser table maps each gateway event to a bound
method and is read by the gateway for every event, so teabot replaces the table's entries once the client is made.
Each wrapper captures what the directory needs, before discord.py's own parser changes its cache, offers it to the
shard's writer, then runs the original.
"""

import logging
from collections.abc import Callable, Mapping, MutableMapping
from datetime import UTC, datetime
from typing import Any

from teabot.core.directory.inbox import (
    AuditEntry,
    Banned,
    Entry,
    Joined,
    Left,
    RoleDeleted,
    Unbanned,
    Updated,
)
from teabot.core.directory.rows import MemberRow

log = logging.getLogger(__name__)

type Offer = Callable[[Entry], None]
type GuildLookup = Callable[[int], Any]


def _cached_roles(guild: Any, user_id: int) -> tuple[int, ...] | None:
    member = guild.get_member(user_id) if guild is not None else None
    if member is None:
        return None
    return tuple(sorted(r.id for r in member.roles if not r.is_default()))


def _user_id(data: Mapping[str, Any]) -> int:
    return int(data["user"]["id"])


def _left(guild_id: int, data: Mapping[str, Any], now: datetime, _guild_of: GuildLookup) -> Entry:
    user = data["user"]
    return Left(guild_id, int(user["id"]), str(user.get("username") or user["id"]), now)


def _updated(guild_id: int, data: Mapping[str, Any], now: datetime, guild_of: GuildLookup) -> Entry:
    member = MemberRow.from_payload(data)
    return Updated(guild_id, member, now, _cached_roles(guild_of(guild_id), member.user_id))


def _role_deleted(guild_id: int, data: Mapping[str, Any], now: datetime, guild_of: GuildLookup) -> Entry:
    role_id = int(data["role_id"])
    guild = guild_of(guild_id)
    role = guild.get_role(role_id) if guild is not None else None
    return RoleDeleted(guild_id, role_id, role.name if role is not None else None, now)


def _audit(guild_id: int, data: Mapping[str, Any], now: datetime, _guild_of: GuildLookup) -> Entry | None:
    if data.get("target_id") is None:
        return None
    actor = data.get("user_id")
    return AuditEntry(
        guild_id,
        int(data["action_type"]),
        int(data["target_id"]),
        int(actor) if actor is not None else None,
        data.get("reason"),
        tuple(data.get("changes") or ()),
        now,
    )


type Capture = Callable[[int, Mapping[str, Any], datetime, GuildLookup], Entry | None]
CAPTURES: Mapping[str, Capture] = {
    "GUILD_MEMBER_ADD": lambda g, data, now, _: Joined(g, MemberRow.from_payload(data), now),
    "GUILD_MEMBER_UPDATE": _updated,
    "GUILD_MEMBER_REMOVE": _left,
    "GUILD_BAN_ADD": lambda g, data, now, _: Banned(g, _user_id(data), now),
    "GUILD_BAN_REMOVE": lambda g, data, now, _: Unbanned(g, _user_id(data), now),
    "GUILD_ROLE_DELETE": _role_deleted,
    "GUILD_AUDIT_LOG_ENTRY_CREATE": _audit,
}


def capture(event: str, data: Mapping[str, Any], guild_of: GuildLookup) -> Entry | None:
    """The directory's entry for one gateway event, read before discord.py applies it."""
    return CAPTURES[event](int(data["guild_id"]), data, datetime.now(UTC), guild_of)


def _wrapped(
    event: str, original: Callable[[Any], Any], offer: Offer, guild_of: GuildLookup
) -> Callable[[Any], Any]:
    def parse(data: Any) -> Any:
        try:
            entry = capture(event, data, guild_of)
            if entry is not None:
                offer(entry)
        except Exception:
            log.exception("directory could not read a gateway event", extra={"event": event})
        return original(data)

    return parse


PARSERS = tuple(CAPTURES)


def install(parsers: MutableMapping[str, Callable[[Any], Any]], offer: Offer, guild_of: GuildLookup) -> bool:
    """Wrap discord.py's parsers in `parsers`, its `ConnectionState.parsers`. Returns False, changing nothing, when
    any is missing, as after a discord.py release that moved them; the directory then relies on its reconcile."""
    missing = [name for name in PARSERS if name not in parsers]
    if missing:
        log.error(
            "directory cannot hear member events: discord.py has no parser for them",
            extra={"missing": missing},
        )
        return False
    for name in PARSERS:
        parsers[name] = _wrapped(name, parsers[name], offer, guild_of)
    return True
