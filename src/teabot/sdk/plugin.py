"""Plugins (D4, D6, D46): a manifest, and a `setup` that registers what the plugin offers.

The registrar grows by addition (D6): each new kind of thing a plugin can offer is a new method, so existing
plugins keep working.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

import discord
from pydantic import BaseModel

from teabot.sdk.actions import ActionSpec
from teabot.sdk.db import Db
from teabot.sdk.ids import check_plugin_id_free


class EmptyConfig(BaseModel):
    """The config of a plugin that has none."""


@dataclass(frozen=True)
class Manifest:
    """What the core needs to know about a plugin before loading it.

    - `id` names the plugin's commands, schema and role, and must be unique in the instance (D46).
    - `version` is the plugin's own version, shown by `teabot plugins list`.
    - `config` is the pydantic model of its per-server config (D10); `EmptyConfig` when it has none.
    - `migrations` is the directory of its numbered SQL migrations (D9), or None when it has no tables.
    """

    id: str
    version: str
    config: type[BaseModel] = EmptyConfig
    migrations: Path | None = None

    def __post_init__(self) -> None:
        check_plugin_id_free(self.id)


class JobContext(Protocol):
    """What one of a plugin's jobs receives."""

    @property
    def guild_id(self) -> int | None:
        """The server the job was queued for."""
        ...

    @property
    def payload(self) -> Mapping[str, Any]:
        """What was queued with the job, as JSON values."""
        ...

    @property
    def db(self) -> Db:
        """The plugin's own tables (D9). As in actions, every query must filter by `guild_id` itself."""
        ...

    @property
    def client(self) -> discord.Client:
        """The bot's Discord client, to find the server's channels and members."""
        ...

    @property
    def config(self) -> BaseModel:
        """The job's server's config for the plugin (D10)."""
        ...

    @property
    def started_by(self) -> int | None:
        """The member who started the job, through an action or a job of theirs, or None."""
        ...

    async def report(self, progress: Mapping[str, Any], /) -> None:
        """Record how far the job has got, which `admin.job_status` shows."""
        ...


type JobHandler = Callable[[JobContext], Awaitable[None]]
"""Runs one job. Raising fails the attempt, and the queue retries it with back-off, five attempts in all (D31)."""


type EventName = Literal[
    "member_join",
    "member_leave",
    "message",
    "reaction_add",
    "reaction_remove",
    "member_roles",
    "voice",
    "enable",
]
"""The Discord events a plugin can handle."""


class Registrar(Protocol):
    """What `setup` registers the plugin's offerings with."""

    def action(self, spec: ActionSpec[Any, Any]) -> None:
        """Offer an action. Its name must start with the plugin's id."""
        ...

    def job(self, name: str, handler: JobHandler) -> None:
        """Handle the plugin's jobs called `name`, which its actions queue with `ctx.queue.schedule`."""
        ...

    def recurring(self, name: str, every: timedelta) -> None:
        """Run the plugin's job `name`, which takes no payload, every `every` in each server where the plugin is
        enabled, the first time one `every` after it is turned on or teabot starts."""
        ...

    def event(self, name: "EventName", handler: JobHandler) -> None:
        """Handle a Discord event in the servers where the plugin is enabled. It runs as a job, `on_<name>`, with
        the event's details in its payload, such as the member's ID as `user_id`."""
        ...


class LoadablePlugin(Protocol):
    """What a package's `teabot.plugins` entry point names (D4): a `Plugin`, or any object with a manifest and a
    setup that registers `ActionSpec`s and jobs."""

    @property
    def manifest(self) -> Manifest:
        """The plugin's id, version, config model and migrations."""
        ...

    def setup(self, registrar: Registrar) -> None:
        """Register the plugin's actions and jobs. Called once per process; raising marks it not loaded."""
        ...
