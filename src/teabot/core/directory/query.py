"""Reading the member directory (D55): structured filters, turned into SQL with every value a parameter, for the
admin tools and, later, plugins' `ctx.members`. No caller's text ever becomes SQL."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from teabot.core.directory.rows import JOIN_SOURCE_NUMBERS, first_id_at
from teabot.sdk.members import MemberFilter

type Status = Literal["present", "left", "everyone"]
type Sort = Literal["joined_newest", "joined_oldest", "name", "left_newest", "created_oldest"]
type GroupBy = Literal["role", "join_method", "inviter", "join_month"]

SORTS: dict[str, str] = {
    "joined_newest": "joined_at DESC NULLS LAST, user_id",
    "joined_oldest": "joined_at ASC NULLS LAST, user_id",
    "name": "lower(coalesce(nickname, global_name, name)), user_id",
    "left_newest": "left_at DESC NULLS LAST, user_id",
    "created_oldest": "user_id",
}
GROUPS: dict[str, str] = {
    "role": "unnest(CASE WHEN role_ids = '{}' THEN ARRAY[0::bigint] ELSE role_ids END)::text",
    "join_method": "coalesce(join_source, 0)::text",
    "inviter": "coalesce(inviter_id, 0)::text",
    "join_month": "coalesce(to_char(joined_at AT TIME ZONE 'UTC', 'YYYY-MM'), 'unknown')",
}
MEMBER_COLUMNS = """
user_id, name, global_name, nickname, bot, role_ids, joined_at, premium_since, timed_out_until, pending,
join_source, source_invite_code, inviter_id, left_at
"""


@dataclass
class Where:
    """WHERE clauses and their parameters, numbered as they are added."""

    clauses: list[str] = field(default_factory=list[str])
    args: list[Any] = field(default_factory=list[Any])

    def arg(self, value: Any) -> str:
        self.args.append(value)
        return f"${len(self.args)}"

    def add(self, clause: str, *values: Any) -> None:
        """Add a clause written with `{}` for each value, in order."""
        self.clauses.append(clause.format(*(self.arg(v) for v in values)))

    def sql(self) -> str:
        return " AND ".join(self.clauses) or "true"


def _escaped(text: str) -> str:
    """`text` in lower case, with LIKE's own characters escaped."""
    return text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _like(text: str) -> str:
    """A case-insensitive LIKE pattern that matches `text` anywhere."""
    return f"%{_escaped(text)}%"


def starts_like(text: str) -> str:
    """A case-insensitive LIKE pattern that matches what starts with `text`."""
    return f"{_escaped(text)}%"


@dataclass(frozen=True)
class Criteria:
    """What the query builder filters by: an SDK `MemberFilter`'s fields, through `criteria`, and `admin.members`'
    own `status`, left days and `name`. Dates are UTC days, inclusive."""

    status: Status = "present"
    roles_any: Sequence[int] = ()
    roles_all: Sequence[int] = ()
    roles_none: Sequence[int] = ()
    no_roles: bool = False
    joined_after: date | None = None
    joined_before: date | None = None
    created_after: date | None = None
    created_before: date | None = None
    left_after: date | None = None
    left_before: date | None = None
    join_methods: Sequence[str] = ()
    invite_code: str | None = None
    inviter_id: int | None = None
    name: str | None = None
    boosting: bool | None = None
    timed_out: bool | None = None
    pending: bool | None = None
    bots: bool | None = None

    @property
    def needs_joins(self) -> bool:
        """Whether it filters by how members joined, which the join-method lookup must be current for."""
        return bool(self.join_methods) or self.invite_code is not None or self.inviter_id is not None


def _day(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def criteria(model: MemberFilter, **extra: Any) -> Criteria:
    """The query builder's criteria from an SDK `MemberFilter`, with `admin.members`' own fields as `extra`."""
    return Criteria(
        roles_any=model.roles_any,
        roles_all=model.roles_all,
        roles_none=model.roles_none,
        no_roles=model.no_roles,
        joined_after=_day(model.joined_after),
        joined_before=_day(model.joined_before),
        created_after=_day(model.created_after),
        created_before=_day(model.created_before),
        join_methods=model.join_method,
        invite_code=model.invite_code,
        inviter_id=model.inviter,
        boosting=model.boosting,
        timed_out=model.timed_out,
        pending=model.pending,
        bots=model.bots,
        **extra,
    )


def _utc(day: date, *, end: bool = False) -> datetime:
    """The start of a UTC day, or with `end` the start of the next."""
    start = datetime.combine(day, time.min, UTC)
    return start + timedelta(days=1) if end else start


def where(guild_id: int, f: Criteria, now: datetime) -> Where:
    """The WHERE clause for a filter in one server."""
    w = Where()
    w.add("guild_id = {}", guild_id)
    if f.status == "present":
        w.add("left_at IS NULL")
    elif f.status == "left":
        w.add("left_at IS NOT NULL")
    _roles(w, f)
    _ranges(w, f)
    _joins(w, f)
    if f.name:
        p = w.arg(_like(f.name))
        w.clauses.append(f"(lower(name) LIKE {p} OR lower(global_name) LIKE {p} OR lower(nickname) LIKE {p})")
    _flags(w, f, now)
    return w


def _roles(w: Where, f: Criteria) -> None:
    if f.roles_any:
        w.add("role_ids && {}::bigint[]", list(f.roles_any))
    if f.roles_all:
        w.add("role_ids @> {}::bigint[]", list(f.roles_all))
    if f.roles_none:
        w.add("NOT role_ids && {}::bigint[]", list(f.roles_none))
    if f.no_roles:
        w.add("role_ids = '{{}}'")


def _joins(w: Where, f: Criteria) -> None:
    if f.join_methods:
        numbers = [JOIN_SOURCE_NUMBERS[m] for m in f.join_methods if m in JOIN_SOURCE_NUMBERS]
        w.add("coalesce(join_source, 0) = ANY({}::integer[])", numbers)
    if f.invite_code is not None:
        w.add("source_invite_code = {}", f.invite_code)
    if f.inviter_id is not None:
        w.add("inviter_id = {}", f.inviter_id)


def _ranges(w: Where, f: Criteria) -> None:
    if f.joined_after:
        w.add("joined_at >= {}", _utc(f.joined_after))
    if f.joined_before:
        w.add("joined_at < {}", _utc(f.joined_before, end=True))
    if f.left_after:
        w.add("left_at >= {}", _utc(f.left_after))
    if f.left_before:
        w.add("left_at < {}", _utc(f.left_before, end=True))
    # An account's ID grows with the time it was made, so its age is a range of IDs.
    if f.created_after:
        w.add("user_id >= {}", first_id_at(_utc(f.created_after)))
    if f.created_before:
        w.add("user_id < {}", first_id_at(_utc(f.created_before, end=True)))


def _flags(w: Where, f: Criteria, now: datetime) -> None:
    for wanted, clause in (
        (f.boosting, "premium_since IS NOT NULL"),
        (f.pending, "pending"),
        (f.bots, "bot"),
    ):
        if wanted is not None:
            w.add(clause if wanted else f"NOT ({clause})")
    if f.timed_out is not None:
        # A timeout ends with no event, so it is compared with the time.
        w.add(("" if f.timed_out else "NOT ") + "coalesce(timed_out_until > {}, false)", now)


def page_sql(w: Where, sort: Sort, limit: int, offset: int) -> str:
    return (
        f"SELECT {MEMBER_COLUMNS} FROM core.members WHERE {w.sql()} ORDER BY {SORTS[sort]} "
        f"LIMIT {int(limit)} OFFSET {int(offset)}"
    )


def count_sql(w: Where) -> str:
    return f"SELECT count(*) FROM core.members WHERE {w.sql()}"


def group_sql(w: Where, group_by: GroupBy) -> str:
    return (
        f"SELECT key, count(*) AS n FROM (SELECT {GROUPS[group_by]} AS key FROM core.members WHERE {w.sql()}) g "
        "GROUP BY key ORDER BY n DESC, key LIMIT 100"
    )


@dataclass(frozen=True)
class HistoryFilter:
    """What `admin.member_history` filters by: one member or the whole server, kinds, and UTC days, inclusive."""

    user_id: int | None = None
    kinds: Sequence[str] = ()
    after: date | None = None
    before: date | None = None


def history_where(guild_id: int, f: HistoryFilter) -> Where:
    w = Where()
    w.add("guild_id = {}", guild_id)
    if f.user_id is not None:
        w.add("user_id = {}", f.user_id)
    if f.kinds:
        w.add("kind = ANY({}::text[])", list(f.kinds))
    if f.after:
        w.add("at >= {}", _utc(f.after))
    if f.before:
        w.add("at < {}", _utc(f.before, end=True))
    return w


def history_sql(w: Where, limit: int, offset: int) -> str:
    return (
        "SELECT user_id, kind, at, since, source, actor_id, reason, detail FROM core.member_events "
        f"WHERE {w.sql()} ORDER BY at DESC LIMIT {int(limit)} OFFSET {int(offset)}"
    )


def history_count_sql(w: Where) -> str:
    return f"SELECT count(*) FROM core.member_events WHERE {w.sql()}"
