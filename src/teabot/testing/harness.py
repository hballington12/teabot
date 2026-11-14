"""A plugin under test (D45): loaded, migrated and invoked through the real loader and call path."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import discord
from pydantic import BaseModel

from teabot.assembly import assemble
from teabot.auth.tokens import Tokens
from teabot.core.loader import from_plugins, load
from teabot.core.queue import Queue
from teabot.core.registry import Call, Registry
from teabot.core.worker import Workers
from teabot.db.migrate import MigrationReport, PluginMigrations, migrate
from teabot.db.naming import Naming
from teabot.db.pool import Pools
from teabot.db.types import Conn
from teabot.sdk import Actor, Plugin
from teabot.sdk.actions import Via
from teabot.testing.fakes import FakeClient, FakeGuild, FakeMember

ENABLE = """
INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled) VALUES ($1, $2, true)
ON CONFLICT (guild_id, plugin_id) DO UPDATE SET enabled = true
"""


class JobFailed(Exception):
    """A job failed while `run_jobs` ran it. The job's own exception is chained as the cause, so its traceback
    shows in the test's output."""


@dataclass
class PluginHarness:
    """One plugin, enabled in one fake server whose first member has Administrator."""

    registry: Registry
    statuses: dict[str, str]
    client: FakeClient
    guild: FakeGuild
    member: FakeMember
    admin: Conn
    pools: Pools
    tokens: Tokens
    workers: Workers
    failures: list[JobFailed] = field(default_factory=list[JobFailed])

    async def invoke(
        self, action: str, raw_input: Mapping[str, Any] | None = None, *, user: int | None = None
    ) -> BaseModel:
        """Run an action as a member would from a slash command."""
        actor = Actor(user if user is not None else self.member.id, "slash")
        return await self.registry.invoke(Call(action, self.guild.id, actor, raw_input or {}))

    async def run_jobs(self, *, raise_failures: bool = True) -> int:
        """Run every due job of the core and this plugin through the real worker path, such as a confirmed
        plan's apply, and return how many ran, the core's own jobs included.

        A job that fails is retried later, as in production, so it does not run again here. With
        `raise_failures`, the first failure is raised as `JobFailed`, with the job's exception as its cause.
        A test that expects a failure passes `raise_failures=False` and checks the job afterwards.
        """
        self.failures.clear()
        ran = 0
        while await self.workers.run_once():
            ran += 1
        if raise_failures and self.failures:
            raise self.failures[0]
        return ran

    async def invoke_with_token(
        self, token: str, action: str, raw_input: Mapping[str, Any] | None = None, *, via: Via = "mcp"
    ) -> BaseModel:
        """Run an action as an MCP client or a backend would with `token`: in its server, as its member,
        within its limits."""
        grant = await self.tokens.check(token)
        actor = Actor(grant.user_id, via, grant.token_id)
        return await self.registry.invoke(Call(action, grant.guild_id, actor, raw_input or {}, grant.limits))


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
    core = assemble(report, pools, Queue(pools.core_db()), client)
    workers = Workers(core.queue, lambda: ["core", plugin_id])
    harness = PluginHarness(
        core.registry, core.statuses, client, guild, member, admin, pools, core.tokens, workers
    )
    for key, handler in list(core.queue.handlers.items()):
        core.queue.handlers[key] = _recording(f"{key[0]}.{key[1]}", handler, harness.failures)
    return harness


def _recording[C](
    name: str, handler: Callable[[C], Awaitable[None]], failures: list[JobFailed]
) -> Callable[[C], Awaitable[None]]:
    """The handler, keeping each failure so `run_jobs` can raise it with its traceback."""

    async def run(ctx: C) -> None:
        try:
            await handler(ctx)
        except Exception as exc:
            failure = JobFailed(f"job {name} failed: {exc!r}")
            failure.__cause__ = exc
            failures.append(failure)
            raise

    return run
