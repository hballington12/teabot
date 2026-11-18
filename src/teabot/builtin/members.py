"""The admin plugin's member directory tools (D55): `admin.members` and `admin.member_history`, for AI assistants and
the service API. Both need Manage Server, as Discord's own member settings do, and every answer says how far the
directory can be trusted.

Before a server's first copy is done, or where the directory is off, they say so instead of answering partially.
Names, nicknames and audit reasons are member-written, so they are `UntrustedText` (D23).
"""

import json
import math
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any, Literal

import discord
from pydantic import BaseModel, Field

from teabot.core.directory import state as states
from teabot.core.directory.labels import LabelService
from teabot.core.directory.plugin_api import resolved
from teabot.core.directory.query import (
    Criteria,
    GroupBy,
    HistoryFilter,
    Sort,
    Status,
    count_sql,
    group_sql,
    history_count_sql,
    history_sql,
    history_where,
    page_sql,
    where,
)
from teabot.core.directory.rows import created_at, join_method
from teabot.db.pool import Database
from teabot.sdk import (
    ActionContext,
    ActionError,
    ActionSpec,
    MemberRef,
    Risk,
    RoleRef,
    Surface,
    UntrustedText,
)
from teabot.sdk.members import MemberFilter

MANAGE_SERVER = discord.Permissions(manage_guild=True)
PAGE = 100
DAY = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="A day, as YYYY-MM-DD, in UTC")
COUNTED = "SELECT count(*) FROM core.members WHERE guild_id = $1 AND left_at IS NULL"

type Kind = Literal[
    "joined", "left", "kicked", "banned", "unbanned", "timeout", "roles", "nickname", "role_deleted"
]
type LookupJoins = Callable[[int], Awaitable[None]]


class MembersQuery(MemberFilter):
    """`MemberFilter`'s fields, which plugins' `ctx.members` takes too, and the admin tool's own."""

    status: Status = Field(default="present", description="Members here now, those who left, or everyone")
    left_after: str | None = DAY
    left_before: str | None = DAY
    name: str | None = Field(
        default=None, max_length=32, description="Username, display name or nickname contains this"
    )
    sort: Sort = "joined_newest"
    group_by: GroupBy | None = Field(
        default=None,
        description="Count members by role, join method, inviter or join month, instead of listing",
    )
    page: int = Field(default=1, ge=1, description="Which page of 100, from 1")


class MemberEntry(BaseModel):
    id: MemberRef
    name: UntrustedText
    display_name: UntrustedText | None
    nickname: UntrustedText | None
    bot: bool
    roles: list[RoleRef]
    joined_at: datetime | None
    account_created: datetime
    join_method: str
    invite_code: UntrustedText | None
    inviter: MemberRef | None
    boosting_since: datetime | None
    timed_out_until: datetime | None
    pending: bool
    left_at: datetime | None


class Group(BaseModel):
    key: str = Field(description="A role's ID, a join method, an inviter's ID or a month; 0 for none")
    label: UntrustedText | None = Field(description="The role's name, for a role")
    count: int


class MembersPage(BaseModel):
    members: list[MemberEntry]
    groups: list[Group] | None = Field(
        description="The counts, when grouped; up to 100 groups, largest first"
    )
    total: int = Field(description="How many members match")
    page: int
    pages: int
    directory: states.DirectoryStatus


class HistoryQuery(BaseModel):
    member: MemberRef | None = Field(
        default=None, description="One member's history; the server's when left out"
    )
    kinds: list[Kind] = Field(default=[], max_length=9, description="Only these kinds of event")
    after: str | None = DAY
    before: str | None = DAY
    page: int = Field(default=1, ge=1, description="Which page of 100, newest first, from 1")


class HistoryEntry(BaseModel):
    member: MemberRef | None = Field(description="Who it happened to; none for a deleted role")
    kind: str
    at: datetime
    since: datetime | None = Field(description="For a change found late: it happened between since and at")
    source: str = Field(
        description="event, heard as it happened, or reconcile, found by comparing with Discord"
    )
    actor: MemberRef | None = Field(description="Who did it, when Discord's audit log said")
    reason: UntrustedText | None
    roles_added: list[RoleRef] = []
    roles_removed: list[RoleRef] = []
    old_nickname: UntrustedText | None = None
    new_nickname: UntrustedText | None = None
    timed_out_until: datetime | None = None
    join_method: str | None = None
    invite_code: UntrustedText | None = None
    inviter: MemberRef | None = None
    role: RoleRef | None = Field(default=None, description="The deleted role")
    role_name: UntrustedText | None = None
    holders: list[MemberRef] = Field(default=[], description="Who held the deleted role")


class HistoryPage(BaseModel):
    events: list[HistoryEntry]
    total: int
    page: int
    pages: int
    directory: states.DirectoryStatus


def _day(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


async def member_filter(data: MembersQuery, guild_id: int, labels: LabelService | None) -> Criteria:
    return await resolved(
        data,
        guild_id,
        labels,
        status=data.status,
        left_after=_day(data.left_after),
        left_before=_day(data.left_before),
        name=data.name,
    )


def entry(row: Any) -> MemberEntry:
    return MemberEntry(
        id=row["user_id"],
        name=row["name"],
        display_name=row["nickname"] or row["global_name"],
        nickname=row["nickname"],
        bot=row["bot"],
        roles=list(row["role_ids"]),
        joined_at=row["joined_at"],
        account_created=created_at(row["user_id"]),
        join_method=join_method(row["join_source"]),
        invite_code=row["source_invite_code"],
        inviter=row["inviter_id"] or None,
        boosting_since=row["premium_since"],
        timed_out_until=row["timed_out_until"],
        pending=row["pending"],
        left_at=row["left_at"],
    )


def history_entry(row: Any) -> HistoryEntry:
    detail: dict[str, Any] = json.loads(row["detail"])
    until = detail.get("until")
    inviter = detail.get("inviter_id")
    role = detail.get("role_id")
    return HistoryEntry(
        member=row["user_id"],
        kind=row["kind"],
        at=row["at"],
        since=row["since"],
        source=row["source"],
        actor=row["actor_id"] or None,
        reason=row["reason"],
        roles_added=[int(r) for r in detail.get("added", ())],
        roles_removed=[int(r) for r in detail.get("removed", ())],
        old_nickname=detail.get("old"),
        new_nickname=detail.get("new"),
        timed_out_until=datetime.fromisoformat(until) if until else None,
        join_method=join_method(detail.get("join_source")) if row["kind"] == "joined" else None,
        invite_code=detail.get("source_invite_code"),
        inviter=int(inviter) if inviter else None,
        role=int(role) if role else None,
        role_name=detail.get("name"),
        holders=[int(h) for h in detail.get("holders", ())],
    )


def _pages(total: int) -> int:
    return max(1, math.ceil(total / PAGE))


class Members:
    """`lookup_joins` reads join methods newer than the last lookup, before a filter by join method; the bot
    process sets it once its directory is open."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.lookup_joins: LookupJoins | None = None
        # Whether a filter's labels count here; the assembly sets it.
        self.labels: LabelService | None = None

    async def _ready(self, guild: discord.Guild) -> states.State:
        """The server's directory state, or a refusal saying why it cannot answer yet."""
        state = await states.load(self.db, guild.id)
        if state.off:
            raise ActionError(
                "The member directory is off in this server, which has more members than this teabot allows."
            )
        if not state.backfilled:
            counted = await self.db.fetchval(COUNTED, guild.id)
            total = guild.member_count or "?"
            raise ActionError(f"The member directory is still filling: {counted} of {total} members so far.")
        return state

    async def members(self, ctx: ActionContext, data: MembersQuery) -> MembersPage:
        state = await self._ready(ctx.guild)
        f = await member_filter(data, ctx.guild.id, self.labels)
        if f.needs_joins and self.lookup_joins is not None:
            await self.lookup_joins(ctx.guild.id)
        w = where(ctx.guild.id, f, datetime.now(UTC))
        total: int = await self.db.fetchval(count_sql(w), *w.args)
        pages = _pages(total)
        groups = None
        rows: list[Any] = []
        if data.group_by is not None:
            groups = [
                self._group(ctx.guild, data.group_by, r)
                for r in await self.db.fetch(group_sql(w, data.group_by), *w.args)
            ]
        else:
            if data.page > pages:
                raise ActionError(f"There are only {pages} pages.")
            rows = await self.db.fetch(page_sql(w, data.sort, PAGE, (data.page - 1) * PAGE), *w.args)
        return MembersPage(
            members=[entry(r) for r in rows],
            groups=groups,
            total=total,
            page=data.page,
            pages=pages,
            directory=states.DirectoryStatus.of(state),
        )

    def _group(self, guild: discord.Guild, group_by: GroupBy, row: Any) -> Group:
        key: str = row["key"]
        label = None
        if group_by == "role" and key != "0":
            role = guild.get_role(int(key))
            label = role.name if role is not None else None
        elif group_by == "join_method":
            key = join_method(int(key) or None)
        return Group(key=key, label=label, count=row["n"])

    async def member_history(self, ctx: ActionContext, data: HistoryQuery) -> HistoryPage:
        state = await self._ready(ctx.guild)
        f = HistoryFilter(
            user_id=data.member, kinds=data.kinds, after=_day(data.after), before=_day(data.before)
        )
        w = history_where(ctx.guild.id, f)
        total: int = await self.db.fetchval(history_count_sql(w), *w.args)
        pages = _pages(total)
        if data.page > pages:
            raise ActionError(f"There are only {pages} pages.")
        rows = await self.db.fetch(history_sql(w, PAGE, (data.page - 1) * PAGE), *w.args)
        return HistoryPage(
            events=[history_entry(r) for r in rows],
            total=total,
            page=data.page,
            pages=pages,
            directory=states.DirectoryStatus.of(state),
        )

    def specs(self) -> dict[str, ActionSpec[Any, Any]]:
        table: list[tuple[str, str, type[BaseModel], type[BaseModel], Any]] = [
            (
                "admin.members",
                "List, filter and count this server's members, and those who left",
                MembersQuery,
                MembersPage,
                self.members,
            ),
            (
                "admin.member_history",
                "Joins, leaves, bans, role and nickname changes here, for one member or everyone",
                HistoryQuery,
                HistoryPage,
                self.member_history,
            ),
        ]
        return {
            name: ActionSpec(
                name,
                summary,
                inp,
                out,
                Risk.READ,
                run,
                default_permissions=MANAGE_SERVER,
                surfaces=Surface.MCP | Surface.SERVICE,
            )
            for name, summary, inp, out, run in table
        }
