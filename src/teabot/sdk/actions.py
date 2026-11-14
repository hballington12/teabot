"""Actions (D1, D17, D21, D29): what a plugin offers, and what each call receives."""

import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import Flag, IntEnum, auto
from typing import Any, Literal, Protocol

import discord
from pydantic import BaseModel

from teabot.sdk.db import Db, Scheduler
from teabot.sdk.ids import PLUGIN_ID_RE
from teabot.sdk.inputs import input_fields
from teabot.sdk.plans import Diff

ACTION_NAME_RE = re.compile(rf"({PLUGIN_ID_RE.pattern})\.([a-z][a-z0-9_]{{0,31}})")


class ActionError(Exception):
    """Raise from an action to tell the member what went wrong. The message is shown to them as written,
    and recorded in the audit log as the error."""


class Risk(IntEnum):
    """How much an action can change (D17). `READ` only looks, `WRITE` adds or changes, and `DESTRUCTIVE`
    removes or overwrites, so it plans first (D21). Ordered, so a token's maximum risk is one comparison."""

    READ = 1
    WRITE = 2
    DESTRUCTIVE = 3


class Surface(Flag):
    """The front doors an action appears on (D1)."""

    SLASH = auto()
    MCP = auto()
    SERVICE = auto()
    ALL = SLASH | MCP | SERVICE


type Via = Literal["slash", "component", "mcp", "service"]
"""The front door a call came through (D1): a slash command, a button, an MCP tool or the service API."""


@dataclass(frozen=True)
class Actor:
    """Who asked. Always a member (D16), even when an LLM client or a backend made the call.

    - `user_id` is the member's Discord ID.
    - `via` is the front door the call came through.
    - `token_id` names the token for MCP and service calls, and is None from Discord.
    """

    user_id: int
    via: Via
    token_id: str | None = None


class ActionContext(Protocol):
    """What one call receives. The core builds it for the one server the call is about (D2)."""

    @property
    def guild(self) -> discord.Guild:
        """The server the call is about."""
        ...

    @property
    def actor(self) -> Actor:
        """The member who made the call."""
        ...

    @property
    def db(self) -> Db:
        """The plugin's own tables (D9). Every query must filter by `guild_id` itself: nothing filters rows for
        the plugin, so a query without the filter sees every server's rows."""
        ...

    @property
    def config(self) -> BaseModel:
        """This server's config for the plugin, an instance of the manifest's `config` model (D10)."""
        ...

    @property
    def queue(self) -> Scheduler:
        """Queues the plugin's jobs for this server (D31)."""
        ...

    async def report(self, progress: Mapping[str, Any], /) -> None:
        """Record how far the action has got. A destructive action's apply runs as a job, and this is its
        progress, which `admin.job_status` shows; elsewhere it does nothing (D21, D31)."""
        ...


@dataclass(frozen=True)
class ActionSpec[I: BaseModel, O: BaseModel]:
    """One action, offered on every front door its `surfaces` allow (D1).

    - `name` is `<plugin id>.<action>` in lower case, such as `announcements.post`.
    - `summary` is the one line members and LLM clients see.
    - `input` and `output` are pydantic models. The input's fields must be of the types D29 allows.
    - `risk` orders the action for tokens (D17). A `DESTRUCTIVE` one must have a `plan` (D21).
    - `run` does the work, given the call's context and its validated input. For a destructive action it is
      the apply, which runs as a job once the member confirms the plan.
    - `default_permissions` are what a member needs, checked on every call.
    - `surfaces` narrows the front doors; all three by default.
    - `plan` returns the diff a destructive action would make, without changing anything.
    - `render` turns the output into the Discord reply; without it the reply lists the output's fields.
    """

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
        """The id of the plugin the action belongs to: its name up to the first dot."""
        return self.name.partition(".")[0]
