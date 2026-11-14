"""Plugins (D4, D6, D46): a manifest, and a `setup` that registers what the plugin offers.

The registrar grows by addition (D6): each new kind of thing a plugin can offer is a new method, so existing
plugins keep working.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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
        """The plugin's own tables, as the job's server's rows only (D9)."""
        ...

    @property
    def client(self) -> discord.Client:
        """The bot's Discord client, to find the server's channels and members."""
        ...

    async def report(self, progress: Mapping[str, Any], /) -> None:
        """Record how far the job has got, which `admin.job_status` shows."""
        ...


type JobHandler = Callable[[JobContext], Awaitable[None]]
"""Runs one job. Raising fails the attempt, and the queue retries it with back-off, five attempts in all (D31)."""


class Registrar(Protocol):
    """What `setup` registers the plugin's offerings with."""

    def action(self, spec: ActionSpec[Any, Any]) -> None:
        """Offer an action. Its name must start with the plugin's id."""
        ...

    def job(self, name: str, handler: JobHandler) -> None:
        """Handle the plugin's jobs called `name`, which its actions queue with `ctx.queue.schedule`."""
        ...


class Plugin(Protocol):
    """A plugin: the object a package's `teabot.plugins` entry point names (D4)."""

    @property
    def manifest(self) -> Manifest:
        """The plugin's id, version, config model and migrations."""
        ...

    def setup(self, registrar: Registrar) -> None:
        """Register the plugin's actions and jobs. Called once per process; raising marks it not loaded."""
        ...
