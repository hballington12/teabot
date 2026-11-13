"""Plugins (D4, D6, D46): a manifest, and a `setup` that registers what the plugin offers.

The registrar grows by addition (D6): event hooks and components arrive with the interaction router.
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import discord
from pydantic import BaseModel

from teapot.sdk.actions import ActionSpec
from teapot.sdk.db import Db
from teapot.sdk.ids import check_plugin_id_free


class EmptyConfig(BaseModel):
    """The config of a plugin that has none."""


@dataclass(frozen=True)
class Manifest:
    id: str
    version: str
    config: type[BaseModel] = EmptyConfig
    migrations: Path | None = None

    def __post_init__(self) -> None:
        check_plugin_id_free(self.id)


class JobContext(Protocol):
    """What one of a plugin's jobs receives."""

    @property
    def guild_id(self) -> int | None: ...

    @property
    def payload(self) -> Mapping[str, Any]: ...

    @property
    def db(self) -> Db: ...

    @property
    def client(self) -> discord.Client: ...

    async def report(self, progress: Mapping[str, Any]) -> None: ...


type JobHandler = Callable[[JobContext], Awaitable[None]]


class Registrar(Protocol):
    def action(self, spec: ActionSpec[Any, Any]) -> None: ...

    def job(self, name: str, handler: JobHandler) -> None: ...


class Plugin(Protocol):
    @property
    def manifest(self) -> Manifest: ...

    def setup(self, registrar: Registrar) -> None: ...
