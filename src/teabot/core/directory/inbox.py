"""What reaches a shard's directory writer (D55): gateway events, captured as they arrive, and a reconcile's pages."""

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from teabot.core.directory.rows import MemberRow


@dataclass(frozen=True)
class Joined:
    guild_id: int
    member: MemberRow
    at: datetime


@dataclass(frozen=True)
class Updated:
    """A member update, with discord.py's cached copy's roles and nickname from just before it, when it had one."""

    guild_id: int
    member: MemberRow
    at: datetime
    cached_roles: tuple[int, ...] | None = None


@dataclass(frozen=True)
class Left:
    guild_id: int
    user_id: int
    name: str
    at: datetime


@dataclass(frozen=True)
class Banned:
    guild_id: int
    user_id: int
    at: datetime


@dataclass(frozen=True)
class Unbanned:
    guild_id: int
    user_id: int
    at: datetime


@dataclass(frozen=True)
class RoleDeleted:
    guild_id: int
    role_id: int
    name: str | None
    at: datetime


@dataclass(frozen=True)
class AuditEntry:
    """One of Discord's audit log entries about a member: who did it, and why."""

    guild_id: int
    action: int
    target_id: int
    actor_id: int | None
    reason: str | None
    changes: tuple[dict[str, Any], ...]
    at: datetime


@dataclass
class Page:
    """One page of a reconcile: the members Discord listed with IDs above `after`, up to `through`, or to the end
    when `through` is None. `older_than` is a minute before its request started: only rows observed before then
    may change. `done` is resolved once the writer has applied it."""

    guild_id: int
    members: list[MemberRow]
    after: int
    through: int | None
    older_than: datetime
    since: datetime
    backfill: bool
    mark_left: bool = True
    done: asyncio.Future[None] = field(default_factory=lambda: asyncio.get_running_loop().create_future())


type Entry = Joined | Updated | Left | Banned | Unbanned | RoleDeleted | AuditEntry | Page
