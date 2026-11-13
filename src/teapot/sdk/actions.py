"""Actions (D1, D17, D21, D29): what a plugin offers, and what each call receives."""

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import Flag, IntEnum, auto
from typing import Any, Literal, Protocol

import discord
from pydantic import BaseModel

from teapot.sdk.db import Db, Scheduler
from teapot.sdk.ids import PLUGIN_ID_RE
from teapot.sdk.inputs import input_fields
from teapot.sdk.plans import Diff

ACTION_NAME_RE = re.compile(rf"({PLUGIN_ID_RE.pattern})\.([a-z][a-z0-9_]{{0,31}})")


class ActionError(Exception):
    """Raise from an action to tell the member what went wrong. The message is shown to them as written,
    and recorded in the audit log as the error."""


class Risk(IntEnum):
    """Ordered, so a token's maximum risk is one comparison (D17)."""

    READ = 1
    WRITE = 2
    DESTRUCTIVE = 3


class Surface(Flag):
    """The front doors an action appears on (D1)."""

    SLASH = auto()
    MCP = auto()
    SERVICE = auto()
    ALL = SLASH | MCP | SERVICE


# The front door a call came through (D1).
type Via = Literal["slash", "component", "mcp", "service"]


@dataclass(frozen=True)
class Actor:
    """Who asked. Always a member (D16)."""

    user_id: int
    via: Via
    token_id: str | None = None


class ActionContext(Protocol):
    """What one call receives. The core builds it for the one server the call is about (D2)."""

    @property
    def guild(self) -> discord.Guild: ...

    @property
    def actor(self) -> Actor: ...

    @property
    def db(self) -> Db: ...

    @property
    def config(self) -> BaseModel: ...

    @property
    def queue(self) -> Scheduler: ...

    async def report(self, progress: Mapping[str, Any], /) -> None:
        """Record how far the action has got. A destructive action's apply runs as a job, and this is its
        progress, which `admin.job_status` shows; elsewhere it does nothing (D21, D31)."""
        ...


@dataclass(frozen=True)
class ActionSpec[I: BaseModel, O: BaseModel]:
    """One action. A destructive one must have a plan (D21); the name is `<plugin id>.<action>`."""

    name: str
    summary: str
    input: type[I]
    output: type[O]
    risk: Risk
    run: Callable[[ActionContext, I], Awaitable[O]]
    default_permissions: discord.Permissions = field(default_factory=discord.Permissions.none)
    surfaces: Surface = Surface.ALL
    plan: Callable[[ActionContext, I], Awaitable[Diff]] | None = None
    render: Callable[[O], discord.Embed | str] | None = None

    def __post_init__(self) -> None:
        if not ACTION_NAME_RE.fullmatch(self.name):
            raise ValueError(f"action name {self.name!r} must be <plugin id>.<action>, in lower case")
        if self.risk is Risk.DESTRUCTIVE and self.plan is None:
            raise ValueError(f"{self.name} is destructive and needs a plan (D21)")
        input_fields(self.input)

    @property
    def plugin_id(self) -> str:
        return self.name.partition(".")[0]
