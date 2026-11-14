"""The admin plugin's lookups (D25, plan): `READ` actions on every surface, so an LLM or a backend finds ids
and follows progress through the same call path as everything else.

- `admin.describe_guild`: channels and roles the member can see, paged, from the cache. No extra permission.
- `admin.find_members`: up to 100 members whose name or nickname starts with the query, from Discord's
  gateway member search. No extra permission.
- `admin.job_status`: a job in this server. Its starter can always see it; other jobs need Manage Server.

Names come from members, so they are `UntrustedText` and MCP wraps them (D23).
"""

import json
import math
from datetime import datetime
from typing import Any, cast

import discord
from pydantic import BaseModel, Field

from teapot.builtin.config import AdminConfig
from teapot.core.registry import ActionSource, find_member, member_permissions
from teapot.db.pool import Database
from teapot.sdk import (
    ActionContext,
    ActionError,
    ActionSpec,
    ChannelRef,
    MemberRef,
    Risk,
    RoleRef,
    UntrustedText,
)

PAGE = 50
JOB = """
SELECT id, plugin_id, handler, state, attempts, progress, last_error, run_at, started_by
FROM core.jobs WHERE id = $1 AND guild_id = $2
"""


class Describe(BaseModel):
    page: int = Field(default=1, ge=1, description="Which page of channels and roles, from 1")


class FindMembers(BaseModel):
    query: str = Field(min_length=1, max_length=32, description="The start of a name or nickname")
    limit: int = Field(default=10, ge=1, le=100, description="At most this many members, up to 100")


class JobStatus(BaseModel):
    job_id: int = Field(description="The job's id, as the action that started it returned")


class ChannelInfo(BaseModel):
    id: ChannelRef
    name: UntrustedText
    kind: str
    category: UntrustedText | None


class RoleInfo(BaseModel):
    id: RoleRef
    name: UntrustedText


class Described(BaseModel):
    channels: list[ChannelInfo]
    roles: list[RoleInfo]
    page: int
    pages: int


class MemberInfo(BaseModel):
    id: MemberRef
    name: UntrustedText
    display_name: UntrustedText


class Found(BaseModel):
    members: list[MemberInfo]


class JobInfo(BaseModel):
    id: int
    plugin: str
    handler: str
    state: str
    attempts: int
    progress: dict[str, Any] | None = Field(description="What the job last reported; null until it reports")
    error: UntrustedText | None
    run_at: datetime


def page_of[T](items: list[T], page: int) -> list[T]:
    return items[(page - 1) * PAGE : page * PAGE]


def page_count(*lists: list[Any]) -> int:
    return max(1, *(math.ceil(len(items) / PAGE) for items in lists))


def listed(channel: Any, member: Any) -> bool:
    """A channel `describe_guild` shows: one the member can see, and not a category, which only groups."""
    return str(channel.type) != "category" and channel.permissions_for(member).view_channel


class Lookups:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def describe_guild(self, ctx: ActionContext, data: Describe) -> Described:
        guild = ctx.guild
        # The member comes from this same guild, so it is the guild's own member type.
        member = cast(discord.Member, await find_member(guild, ctx.actor.user_id))
        channels = [
            ChannelInfo(
                id=c.id, name=c.name, kind=str(c.type), category=c.category.name if c.category else None
            )
            for c in guild.channels
            if listed(c, member)
        ]
        roles = [RoleInfo(id=r.id, name=r.name) for r in guild.roles if r.id != guild.id]
        pages = page_count(channels, roles)
        if data.page > pages:
            raise ActionError(f"There are only {pages} pages.")
        return Described(
            channels=page_of(channels, data.page),
            roles=page_of(roles, data.page),
            page=data.page,
            pages=pages,
        )

    async def find_members(self, ctx: ActionContext, data: FindMembers) -> Found:
        found = await ctx.guild.query_members(data.query, limit=data.limit)
        return Found(members=[MemberInfo(id=m.id, name=m.name, display_name=m.display_name) for m in found])

    async def job_status(self, ctx: ActionContext, data: JobStatus) -> JobInfo:
        row = await self.db.fetchrow(JOB, data.job_id, ctx.guild.id)
        if row is None:
            raise ActionError(f"There is no job {data.job_id} in this server.")
        starter = row["started_by"] == ctx.actor.user_id
        if not starter and not (await member_permissions(ctx.guild, ctx.actor.user_id)).manage_guild:
            raise ActionError("Seeing someone else's job needs Manage Server.")
        return JobInfo(
            id=row["id"],
            plugin=row["plugin_id"],
            handler=row["handler"],
            state=row["state"],
            attempts=row["attempts"],
            progress=None if row["progress"] is None else json.loads(row["progress"]),
            error=row["last_error"],
            run_at=row["run_at"],
        )

    def sources(self) -> dict[str, ActionSource]:
        table: list[tuple[str, str, type[BaseModel], type[BaseModel], Any]] = [
            (
                "admin.describe_guild",
                "Channels and roles you can see here",
                Describe,
                Described,
                self.describe_guild,
            ),
            (
                "admin.find_members",
                "Find members by the start of their name",
                FindMembers,
                Found,
                self.find_members,
            ),
            ("admin.job_status", "The progress of a job here", JobStatus, JobInfo, self.job_status),
        ]
        specs = {
            name: ActionSpec(name, summary, inp, out, Risk.READ, run)
            for name, summary, inp, out, run in table
        }
        return {"admin": ActionSource(AdminConfig, specs, builtin=True)}
