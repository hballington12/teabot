"""A member as the directory stores it (D55), read from Discord's member object, which the gateway and the REST member
list send in the same shape."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from teabot.db.types import Record

# Discord's join_source_type numbers, as its member search returns them (S9). An unknown number keeps its value.
JOIN_SOURCES: Mapping[int, str] = {
    0: "unknown",
    1: "bot",
    2: "integration",
    3: "discovery",
    4: "hub",
    5: "invite",
    6: "vanity_url",
    7: "manual_verification",
}
JOIN_SOURCE_NUMBERS: Mapping[str, int] = {name: number for number, name in JOIN_SOURCES.items()}
COLUMNS = (
    "name, global_name, nickname, bot, role_ids, joined_at, premium_since, timed_out_until, pending, flags"
)


def join_method(source: int | None) -> str:
    """The name of a join method, `unknown` when none was found, and `source_<n>` for a number Discord added."""
    if source is None:
        return "unknown"
    return JOIN_SOURCES.get(source, f"source_{source}")


def timestamp(value: Any) -> datetime | None:
    """A time Discord sends as ISO 8601 text, or None."""
    if not value:
        return None
    return datetime.fromisoformat(str(value)).astimezone(UTC)


def created_at(user_id: int) -> datetime:
    """When a Discord account was made, from its ID."""
    return datetime.fromtimestamp(((user_id >> 22) + 1420070400000) / 1000, UTC)


def first_id_at(when: datetime) -> int:
    """The lowest ID Discord could give an account made at `when`, for filtering by account age."""
    ms = int(when.timestamp() * 1000) - 1420070400000
    return max(ms, 0) << 22


@dataclass(frozen=True)
class MemberRow:
    """What the directory keeps of one member, as Discord described them."""

    user_id: int
    name: str
    global_name: str | None
    nickname: str | None
    bot: bool
    role_ids: tuple[int, ...]
    joined_at: datetime | None
    premium_since: datetime | None
    timed_out_until: datetime | None
    pending: bool
    flags: int

    @classmethod
    def from_payload(cls, data: Mapping[str, Any]) -> "MemberRow":
        """From Discord's guild member object, with its `user`."""
        user = data["user"]
        return cls(
            user_id=int(user["id"]),
            name=str(user.get("username") or user["id"]),
            global_name=user.get("global_name"),
            nickname=data.get("nick"),
            bot=bool(user.get("bot", False)),
            role_ids=tuple(sorted(int(r) for r in data.get("roles", ()))),
            joined_at=timestamp(data.get("joined_at")),
            premium_since=timestamp(data.get("premium_since")),
            timed_out_until=timestamp(data.get("communication_disabled_until")),
            pending=bool(data.get("pending", False)),
            flags=int(data.get("flags", 0)),
        )

    @classmethod
    def from_record(cls, row: Record) -> "MemberRow":
        return cls(
            user_id=row["user_id"],
            name=row["name"],
            global_name=row["global_name"],
            nickname=row["nickname"],
            bot=row["bot"],
            role_ids=tuple(sorted(row["role_ids"])),
            joined_at=row["joined_at"],
            premium_since=row["premium_since"],
            timed_out_until=row["timed_out_until"],
            pending=row["pending"],
            flags=row["flags"],
        )

    def values(self) -> tuple[Any, ...]:
        """The row's values in the order of `COLUMNS`."""
        return (
            self.name,
            self.global_name,
            self.nickname,
            self.bot,
            list(self.role_ids),
            self.joined_at,
            self.premium_since,
            self.timed_out_until,
            self.pending,
            self.flags,
        )
