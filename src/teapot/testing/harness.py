"""A plugin under test (D45): loaded, migrated and invoked through the real loader and call path."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import discord
from pydantic import BaseModel

from teapot.core.audit import AuditLog
from teapot.core.config import ConfigStore
from teapot.core.loader import from_plugins, load
from teapot.core.queue import Queue
from teapot.core.registry import Call, Registry
from teapot.db.migrate import MigrationReport, PluginMigrations, migrate
from teapot.db.naming import Naming
from teapot.db.pool import Pools
from teapot.db.types import Conn
from teapot.sdk import Actor, Plugin
from teapot.testing.fakes import FakeClient, FakeGuild, FakeMember

ENABLE = """
INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled) VALUES ($1, $2, true)
ON CONFLICT (guild_id, plugin_id) DO UPDATE SET enabled = true
"""


@dataclass
class PluginHarness:
    """One plugin, enabled in one fake server whose first member has Administrator."""

    registry: Registry
    client: FakeClient
    guild: FakeGuild
    member: FakeMember
    admin: Conn
    pools: Pools

    async def invoke(
        self, action: str, raw_input: Mapping[str, Any] | None = None, *, user: int | None = None
    ) -> BaseModel:
        """Run an action as a member would from a slash command."""
        actor = Actor(user if user is not None else self.member.id, "slash")
        return await self.registry.invoke(Call(action, self.guild.id, actor, raw_input or {}))


async def build_harness(plugin: Plugin, *, admin: Conn, naming: Naming, pools: Pools) -> PluginHarness:
    """Load `plugin` through the real loader, or raise with the reason it did not load."""

    async def migrator(plugins: Sequence[PluginMigrations]) -> MigrationReport:
        return await migrate(admin, naming, plugins)

    report = await load(from_plugins([plugin]), disabled=(), migrate_with=migrator)
    plugin_id = plugin.manifest.id
    status = report.statuses[plugin_id]
    if not status.loaded:
        raise RuntimeError(f"{plugin_id} did not load ({status.reason}): {status.error}")
    guild = FakeGuild()
    member = guild.add_member(discord.Permissions.all())
    client = FakeClient({guild.id: guild})
    await admin.execute(ENABLE, guild.id, plugin_id)
    registry = Registry(
        report.loaded,
        pools=pools,
        config=ConfigStore(pools.core_db()),
        client=client,
        audit=AuditLog(Queue(pools.core_db())),
    )
    return PluginHarness(registry, client, guild, member, admin, pools)
