"""A plugin under test (D45): loaded, migrated and invoked through the real loader and call path."""

import json
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import discord
from pydantic import BaseModel

from teabot.assembly import assemble
from teabot.auth.tokens import Tokens
from teabot.core.events import Events
from teabot.core.loader import from_plugins, load
from teabot.core.outbox import POST_MESSAGE, Outbox
from teabot.core.plans import Planned
from teabot.core.queue import Queue
from teabot.core.registry import Call, Registry
from teabot.core.worker import Workers
from teabot.db.migrate import MigrationReport, PluginMigrations, migrate
from teabot.db.naming import Naming
from teabot.db.pool import Pools
from teabot.db.types import Conn
from teabot.lint import check_package
from teabot.sdk import DESTRUCTIVE, Action, Actor, Choice, LoadablePlugin
from teabot.sdk._clock import CLOCK
from teabot.sdk.actions import Via
from teabot.sdk.components import parse_custom_id, parse_select_id
from teabot.sdk.db import Bound
from teabot.sdk.plugin import EventName
from teabot.testing.fakes import (
    FakeButton,
    FakeChannel,
    FakeClient,
    FakeGuild,
    FakeMember,
    FakeMessage,
    FakeRole,
    FakeSelect,
    next_id,
)

ENABLE = """
INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled) VALUES ($1, $2, true)
ON CONFLICT (guild_id, plugin_id) DO UPDATE SET enabled = true
"""


# The outbox's jobs that are due, oldest first, marked done as the harness sends them itself.
DUE_POSTS = """
UPDATE core.jobs SET state = 'done', finished_at = now()
WHERE id IN (
    SELECT id FROM core.jobs WHERE plugin_id = 'core' AND handler = $1 AND state = 'pending' AND run_at <= now()
)
RETURNING id, payload
"""


RUN_NOW = """
INSERT INTO core.jobs (guild_id, plugin_id, handler, run_at, payload, started_by)
VALUES ($1, $2, $3, now(), $4::jsonb, $5)
"""


class CheckFailed(Exception):
    """The plugin's code fails the review checklist that `teabot check` runs. The message lists each problem with
    its file and line."""


def lint_plugin(plugin: LoadablePlugin) -> None:
    """Run `teabot check` on the package that made a `Plugin`: the module itself when it is a package, or the
    package holding it. A plugin written inside a test module is not checked."""
    home = getattr(plugin, "home", None) or getattr(plugin, "_module", None) or ""
    package = home if hasattr(sys.modules.get(home), "__path__") else home.rpartition(".")[0]
    file = getattr(sys.modules.get(package), "__file__", None)
    if not package or package.split(".", 1)[0] in ("tests", "test") or file is None:
        return
    problems = check_package(Path(file).parent)
    if problems:
        raise CheckFailed("\n".join(str(p) for p in problems))


class JobFailed(Exception):
    """A job failed while `run_jobs` ran it. The job's own exception is chained as the cause, so its traceback
    shows in the test's output."""


type HarnessFactory = Callable[[LoadablePlugin], Awaitable["PluginHarness"]]
"""The `teabot_harness` fixture: `await teabot_harness(plugin)` gives a `PluginHarness`."""


@dataclass
class PluginHarness:
    """One plugin, enabled in one fake server whose first member owns it and has Administrator."""

    registry: Registry
    statuses: dict[str, str]
    client: FakeClient
    guild: FakeGuild
    member: FakeMember
    admin: Conn
    pools: Pools
    tokens: Tokens
    workers: Workers
    plugin_id: str = ""
    events: Events | None = None
    outbox: Outbox | None = None
    failures: list[JobFailed] = field(default_factory=list[JobFailed])
    _plans: dict[str, tuple[str, dict[str, Any], int]] = field(
        default_factory=dict[str, tuple[str, dict[str, Any], int]]
    )

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

    async def send_posts(self) -> int:
        """Send the posts the plugin has queued with `tx.send`, `tx.edit` and `tx.delete`, and nothing else, and
        return how many. `call`, `press` and `choose` do this before they return; `run_jobs` sends them too."""
        assert self.outbox is not None
        rows = await self.admin.fetch(DUE_POSTS, POST_MESSAGE)
        for post_id in dict.fromkeys(int(json.loads(r["payload"])["post_id"]) for r in rows):
            await self.outbox.deliver(post_id)
        return len(rows)

    async def call[**P, R](self, action: Action[Any, P, R], /, *args: P.args, **kwargs: P.kwargs) -> R:
        """Run a decorated action as the server's owner, its first member, who has Administrator, through the
        real call path. Returns what the action's function returned, once the posts it queued are sent. A
        refusal raises `Refused`, and an `ActionError` raises `ActionFailed`. A destructive action goes through
        `plan` and `confirm` instead."""
        return await self.as_member(self.member).call(action, *args, **kwargs)

    async def plan[**P](self, action: Action[Any, P, Any], /, *args: P.args, **kwargs: P.kwargs) -> Planned:
        """Ask a destructive action for its plan, as the server's first member."""
        return await self.as_member(self.member).plan(action, *args, **kwargs)

    async def confirm(self, plan: Planned) -> None:
        """Confirm a plan as the member who asked for it, and run the apply. A failed apply raises `JobFailed`."""
        action, raw, user = self._plans[plan.confirm]
        outcome = await self.registry.invoke(
            Call(action, self.guild.id, Actor(user, "component"), raw | {"confirm": plan.confirm})
        )
        if isinstance(outcome, Planned):
            raise RuntimeError(f"the plan was stale; the fresh plan has confirm value {outcome.confirm}")
        await self.run_jobs()

    async def run_job(self, job: Bound) -> None:
        """Run one of the plugin's jobs now, with these arguments, through the real worker, as the first member
        had scheduled it. Run it after the job's own run to test that a second run changes nothing. A failure
        raises `JobFailed`."""
        await self.admin.execute(
            RUN_NOW, self.guild.id, self.plugin_id, job.handler, json.dumps(job.payload), self.member.id
        )
        await self.run_jobs()

    async def press(self, button: FakeButton, /) -> str:
        """Press a button on a fake message as the server's first member, through the real call path, as Discord
        would on a click. Returns the reply they would see."""
        return await self.as_member(self.member).press(button)

    async def choose(self, select: FakeSelect, values: Sequence[Any], /) -> str:
        """Choose from a select menu on a fake message as the server's first member. Returns the reply they would
        see."""
        return await self.as_member(self.member).choose(select, values)

    async def join(self, member: FakeMember) -> None:
        """Fire a member joining the server, as Discord would, and run the jobs it queues. Add the member to
        `harness.guild` first."""
        assert self.events is not None
        await self.events.fire(self.guild.id, "member_join", {"user_id": member.id})
        await self.run_jobs()

    async def leave(self, member: FakeMember) -> None:
        """Take the member out of the server, fire them leaving, as Discord would, and run the jobs it queues."""
        assert self.events is not None
        self.guild.members.pop(member.id, None)
        self.guild.fetchable.pop(member.id, None)
        await self.events.fire(self.guild.id, "member_leave", {"user_id": member.id, "name": member.name})
        await self.run_jobs()

    async def enable(self) -> None:
        """Turn the plugin on in the fake server as `/plugins enable` would, as the first member, and run its
        enable handler. The harness starts with the plugin on without running it."""
        await self.admin.execute(
            "UPDATE core.guild_plugins SET enabled = false WHERE guild_id = $1 AND plugin_id = $2",
            self.guild.id,
            self.plugin_id,
        )
        await self.invoke("plugins.enable", {"plugin": self.plugin_id})
        await self.run_jobs()

    async def _fire(self, event: EventName, payload: Mapping[str, Any]) -> None:
        assert self.events is not None
        await self.events.fire(self.guild.id, event, payload)
        await self.run_jobs()

    async def post(self, channel: FakeChannel, author: FakeMember, content: str) -> FakeMessage:
        """Post a message in a fake channel as `author`, fire it, as Discord would, and run the jobs it queues.
        Returns the message, to react to."""
        message = FakeMessage(next_id(), channel.id, content, None, author_id=author.id)
        channel.sent.append(message)
        payload = {
            "message_id": message.id,
            "channel_id": channel.id,
            "author_id": author.id,
            "content": content,
        }
        await self._fire("message", payload)
        return message

    async def react(
        self, message: FakeMessage, member: FakeMember, emoji: str, *, remove: bool = False
    ) -> None:
        """Add `member`'s reaction to a fake message, or with `remove` take it off, fire it and run its jobs."""
        payload = {
            "message_id": message.id,
            "channel_id": message.channel_id,
            "user_id": member.id,
            "emoji": emoji,
        }
        await self._fire("reaction_remove" if remove else "reaction_add", payload)

    async def change_roles(
        self, member: FakeMember, *, added: Sequence[FakeRole] = (), removed: Sequence[FakeRole] = ()
    ) -> None:
        """Give and take roles as Discord would when someone else changes them, fire it and run its jobs."""
        gone = {r.id for r in removed}
        member.roles = [r for r in member.roles if r.id not in gone] + [
            r for r in added if r not in member.roles
        ]
        payload = {"user_id": member.id, "added": [r.id for r in added], "removed": [r.id for r in removed]}
        await self._fire("member_roles", payload)

    async def voice(self, member: FakeMember, *, joined: Any = None, left: Any = None) -> None:
        """Move `member` into the voice channel `joined`, out of `left`, or both, fire it and run its jobs."""
        payload = {"user_id": member.id, "joined": _id_or_none(joined), "left": _id_or_none(left)}
        await self._fire("voice", payload)

    async def autocomplete(
        self, action: Action[Any, ..., Any], option: str, typed: str = ""
    ) -> list[Choice[Any]]:
        """The suggestions a member sees for `option` after typing `typed`, through the real path: nothing when
        the action would be refused, or its suggester fails."""
        return await self.registry.suggest(action.name, self.guild.id, self.member.id, option, typed)

    def as_member(self, member: FakeMember) -> "MemberCalls":
        """Calls made as `member` rather than the first member."""
        return MemberCalls(self, member.id)

    async def configure(self, config: BaseModel) -> None:
        """Store this server's config for the plugin, as an admin's `/plugins config` would."""
        await self.admin.execute(CONFIGURE, self.guild.id, self.plugin_id, config.model_dump_json())

    async def advance(self, *, days: int = 0, hours: int = 0, minutes: int = 0, seconds: int = 0) -> None:
        """Move time forward: `ctx.now`, `now()` in the plugin's SQL, when scheduled jobs fall due, and how old
        plans are. Jobs that fall due run at the next `run_jobs`."""
        step = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
        CLOCK.offset += step
        await self.admin.execute(
            "UPDATE core.jobs SET run_at = run_at - $1::interval WHERE state = 'pending'", step
        )
        await self.admin.execute(
            "UPDATE core.audit_log SET time = time - $1::interval WHERE outcome = 'planned'", step
        )
        await install_clock(self.admin, self.pools.naming, self.plugin_id, CLOCK.offset)

    async def invoke_with_token(
        self, token: str, action: str, raw_input: Mapping[str, Any] | None = None, *, via: Via = "mcp"
    ) -> BaseModel:
        """Run an action as an MCP client or a backend would with `token`: in its server, as its member,
        within its limits."""
        grant = await self.tokens.check(token)
        actor = Actor(grant.user_id, via, grant.token_id)
        return await self.registry.invoke(Call(action, grant.guild_id, actor, raw_input or {}, grant.limits))


CONFIGURE = "UPDATE core.guild_plugins SET config = $3::jsonb WHERE guild_id = $1 AND plugin_id = $2"


async def install_clock(admin: Conn, naming: Naming, plugin_id: str, offset: timedelta) -> None:
    """A `now()` in the plugin's schema, ahead of Postgres's own on its search path, moved by the test clock.
    Only test databases get it."""
    schema = naming.plugin_schema(plugin_id)
    seconds = int(offset.total_seconds())
    await admin.execute(
        f'CREATE OR REPLACE FUNCTION "{schema}".now() RETURNS timestamptz LANGUAGE sql STABLE '
        f"AS $$ SELECT pg_catalog.now() + make_interval(secs => {seconds}) $$"
    )
    await admin.execute(
        f'GRANT EXECUTE ON FUNCTION "{schema}".now() TO "{naming.plugin_runtime_role(plugin_id)}"'
    )


@dataclass(frozen=True)
class MemberCalls:
    """A harness's calls, made as one member."""

    harness: PluginHarness
    user: int

    async def call[**P, R](self, action: Action[Any, P, R], /, *args: P.args, **kwargs: P.kwargs) -> R:
        """Run a decorated action as this member. See `PluginHarness.call`."""
        if args:
            raise TypeError("harness.call takes an action's inputs by name")
        if action.risk is DESTRUCTIVE:
            raise TypeError(f"{action.name} is destructive: use harness.plan, then harness.confirm")
        out = await self._invoke(action, kwargs)
        await self.harness.send_posts()
        return action.output.unwrap(out)

    async def plan[**P](self, action: Action[Any, P, Any], /, *args: P.args, **kwargs: P.kwargs) -> Planned:
        """Ask a destructive action for its plan as this member."""
        if args:
            raise TypeError("harness.plan takes an action's inputs by name")
        raw = _raw(action, kwargs)
        out = await self.harness.registry.invoke(
            Call(action.name, self.harness.guild.id, Actor(self.user, "slash"), raw)
        )
        if not isinstance(out, Planned):
            raise TypeError(f"{action.name} is not destructive, so it has no plan: use harness.call")
        self.harness._plans[out.confirm] = (action.name, raw, self.user)  # pyright: ignore[reportPrivateUsage]
        return out

    async def press(self, button: FakeButton, /) -> str:
        """Press a button on a fake message as this member, through the real call path. Returns the reply they
        would see. A refusal raises `Refused`, and an `ActionError` raises `ActionFailed`."""
        bound = parse_custom_id(button.custom_id)
        if bound is None:
            raise ValueError(f"{button.custom_id!r} is not one of teabot's buttons")
        call = Call(bound.action, self.harness.guild.id, Actor(self.user, "component"), dict(bound.input))
        out = await self.harness.registry.invoke(call)
        await self.harness.send_posts()
        return self._shown(bound.action, out)

    async def choose(self, select: FakeSelect, values: Sequence[Any], /) -> str:
        """Choose from a select menu on a fake message as this member: option values for a menu of options, or
        roles, channels or members for Discord's own pickers. Returns the reply they would see."""
        parsed = parse_select_id(select.custom_id)
        if parsed is None:
            raise ValueError(f"{select.custom_id!r} is not one of teabot's select menus")
        bound, into = parsed
        chosen = [str(getattr(v, "id", v)) for v in values]
        raw = dict(bound.input) | {into: chosen}
        call = Call(bound.action, self.harness.guild.id, Actor(self.user, "component"), raw)
        out = await self.harness.registry.invoke(call)
        await self.harness.send_posts()
        return self._shown(bound.action, out)

    async def autocomplete(
        self, action: Action[Any, ..., Any], option: str, typed: str = ""
    ) -> list[Choice[Any]]:
        """The suggestions this member sees for `option` after typing `typed`: none when they may not run the
        action."""
        return await self.harness.registry.suggest(
            action.name, self.harness.guild.id, self.user, option, typed
        )

    def _shown(self, action: str, out: BaseModel) -> str:
        spec = self.harness.registry.actions[action]
        shown = spec.render(out) if spec.render is not None else out.model_dump_json()
        return shown if isinstance(shown, str) else str(shown.description or shown.title or "")

    async def _invoke(self, action: Action[Any, ..., Any], kwargs: Mapping[str, Any]) -> BaseModel:
        call = Call(action.name, self.harness.guild.id, Actor(self.user, "slash"), _raw(action, kwargs))
        return await self.harness.registry.invoke(call)


def _id_or_none(channel: Any) -> int | None:
    return None if channel is None else int(getattr(channel, "id", channel))


def _raw(action: Action[Any, ..., Any], kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """An action's inputs as a member would send them: Discord objects as their IDs."""
    resolved = {r.name for r in action.inputs.resolved}
    return {name: (as_ids(value) if name in resolved else value) for name, value in kwargs.items()}


def as_ids(value: Any) -> Any:
    """A Discord object as its ID, and a list of them as a list of IDs."""
    if isinstance(value, list | tuple):
        return [item.id for item in cast(list[Any], value)]
    return value.id if value is not None else None


async def build_harness(
    plugin: LoadablePlugin, *, admin: Conn, naming: Naming, pools: Pools
) -> PluginHarness:
    """Load `plugin` through the real loader, or raise with the reason it did not load."""

    async def migrator(plugins: Sequence[PluginMigrations]) -> MigrationReport:
        return await migrate(admin, naming, plugins)

    lint_plugin(plugin)
    report = await load(from_plugins([plugin]), disabled=(), migrate_with=migrator)
    plugin_id = plugin.manifest.id
    status = report.statuses[plugin_id]
    if not status.loaded:
        raise RuntimeError(f"{plugin_id} did not load ({status.reason}): {status.error}")
    guild = FakeGuild()
    member = guild.add_member(discord.Permissions.all())
    guild.owner_id = member.id
    client = FakeClient({guild.id: guild})
    await admin.execute(ENABLE, guild.id, plugin_id)
    core = assemble(report, pools, Queue(pools.core_db()), client)
    workers = Workers(core.queue, lambda: ["core", plugin_id])
    harness = PluginHarness(
        core.registry,
        core.statuses,
        client,
        guild,
        member,
        admin,
        pools,
        core.tokens,
        workers,
        plugin_id,
        core.events,
        core.outbox,
    )
    await install_clock(admin, naming, plugin_id, CLOCK.offset)
    await core.recurring.ensure(guild.id, plugin_id)
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
