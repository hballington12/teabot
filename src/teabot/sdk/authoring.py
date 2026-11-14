"""Writing a plugin (D4, D45): a `Plugin`, and functions decorated as its actions and jobs.

```python
plugin = Plugin("giveaways", config=Cfg)
type Ctx = Context[Cfg]

@plugin.action(risk=WRITE, needs="manage_messages")
async def start(ctx: Ctx, channel: TextChannel, prize: str) -> Started:
    \"\"\"Start a giveaway.

    Args:
        channel: Where to announce it.
        prize: What the winner gets.
    \"\"\"
```

Each decorated function becomes an `ActionSpec` or a job handler when the plugin is set up, so the core keeps
one model of an action whichever way a plugin was written.
"""

import importlib.metadata
import inspect
import json
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Concatenate, Generic, Literal, Protocol, get_args

import discord
from pydantic import BaseModel
from typing_extensions import TypeVar

from teabot.sdk._signature import (
    Inputs,
    Output,
    SignatureError,
    read_inputs,
    read_output,
    resolve,
    unalias,
    where,
)
from teabot.sdk._views import guild_view
from teabot.sdk.actions import SYSTEM, ActionContext, ActionError, ActionSpec, Actor, Risk
from teabot.sdk.db import Bound, Db
from teabot.sdk.guild import Guild
from teabot.sdk.plans import Diff
from teabot.sdk.plugin import EmptyConfig, JobContext, Manifest, Registrar

READ = Risk.READ
WRITE = Risk.WRITE
DESTRUCTIVE = Risk.DESTRUCTIVE

type Permission = Literal[
    "add_reactions", "administrator", "attach_files", "ban_members", "bypass_slowmode", "change_nickname",
    "connect", "create_events", "create_expressions", "create_instant_invite", "create_polls",
    "create_private_threads", "create_public_threads", "deafen_members", "embed_links", "external_emojis",
    "external_stickers", "kick_members", "manage_channels", "manage_emojis", "manage_emojis_and_stickers",
    "manage_events", "manage_expressions", "manage_guild", "manage_messages", "manage_nicknames",
    "manage_permissions", "manage_roles", "manage_threads", "manage_webhooks", "mention_everyone",
    "moderate_members", "move_members", "mute_members", "pin_messages", "priority_speaker",
    "read_message_history", "read_messages", "request_to_speak", "send_messages", "send_messages_in_threads",
    "send_polls", "send_tts_messages", "send_voice_messages", "set_voice_channel_status", "speak", "stream",
    "use_application_commands", "use_embedded_activities", "use_external_apps", "use_external_emojis",
    "use_external_sounds", "use_external_stickers", "use_soundboard", "use_voice_activation", "view_audit_log",
    "view_channel", "view_creator_monetization_analytics", "view_guild_insights",
]  # fmt: skip
"""A Discord permission a member needs for an action, by discord.py's name for it."""

Cfg = TypeVar("Cfg", bound=BaseModel, default=EmptyConfig)


class Context[C: BaseModel](Protocol):
    """What an action or a job receives, for one server (D2)."""

    @property
    def guild(self) -> Guild:
        """The server the call is about."""
        ...

    @property
    def actor(self) -> Actor:
        """Who made the call, and through which front door."""
        ...

    @property
    def config(self) -> C:
        """This server's config for the plugin (D10)."""
        ...

    @property
    def db(self) -> Db:
        """The plugin's own tables (D9). Every query filters by `guild_id`."""
        ...

    @property
    def now(self) -> datetime:
        """The current time, in UTC."""
        ...

    @property
    def diff(self) -> Diff:
        """In a destructive action's apply, the diff of the plan the member confirmed, whose entries' keys say what
        to change; empty elsewhere."""
        ...

    async def report(self, progress: Mapping[str, Any], /) -> None:
        """Record how far a long change has got, which `/admin job_status` shows."""
        ...


@dataclass
class _Context:
    guild: Guild
    actor: Actor
    config: Any
    open_db: Callable[[], Db]
    reporter: Callable[[Mapping[str, Any]], Awaitable[None]]
    diff: Diff = field(default_factory=Diff)
    now: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def db(self) -> Db:
        return self.open_db()

    async def report(self, progress: Mapping[str, Any], /) -> None:
        await self.reporter(progress)


def _permissions(needs: Permission | tuple[Permission, ...]) -> discord.Permissions:
    names = (needs,) if isinstance(needs, str) else needs
    return discord.Permissions(**dict.fromkeys(names, True))


@dataclass
class Action[C: BaseModel, **P, R]:
    """A decorated action, which `@plugin.action` returns. `.plan` attaches a destructive action's plan.

    - `func` is the decorated function, and `name` its full name, such as `giveaways.start`.
    - `risk`, `needs` and `reply` are as the decorator was given them.
    - `inputs` and `output` are read from the function's signature and docstring.
    - `planner` is the plan `.plan` attached, if any.
    """

    func: Callable[Concatenate[Context[C], P], Awaitable[R]]
    name: str
    risk: Risk
    needs: discord.Permissions
    reply: Literal["private", "public"]
    inputs: Inputs
    output: Output
    planner: Callable[..., Awaitable[Diff]] | None = None

    def plan(
        self, func: Callable[Concatenate[Context[C], P], Awaitable[Diff]]
    ) -> Callable[..., Awaitable[Diff]]:
        """Attach the plan of a destructive action: the change it would make, computed without making it (D21).
        It takes the same inputs as the action."""
        self.planner = func
        return func

    def spec(self) -> ActionSpec[Any, Any]:
        """The action as the core's model of one."""
        planner = self.planner
        return ActionSpec(
            self.name,
            self.inputs.summary,
            self.inputs.model,
            self.output.model,
            self.risk,
            self._run,
            default_permissions=self.needs,
            plan=self._plan if planner is not None else None,
            render=self.output.render,
            reply=self.reply,
        )

    async def _run(self, ctx: ActionContext, data: BaseModel) -> BaseModel:
        context = _context_of(ctx)
        arguments = await _arguments(self.inputs, context, data)
        func: Callable[..., Awaitable[Any]] = self.func
        return self.output.wrap(await func(**arguments))

    async def _plan(self, ctx: ActionContext, data: BaseModel) -> Diff:
        assert self.planner is not None
        return await self.planner(**await _arguments(self.inputs, _context_of(ctx), data))


def _context_of(ctx: ActionContext) -> _Context:
    diff = getattr(ctx, "diff", None) or Diff()
    return _Context(guild_view(ctx.guild), ctx.actor, ctx.config, lambda: ctx.db, ctx.report, diff)


async def _arguments(inputs: Inputs, context: _Context, data: BaseModel) -> dict[str, Any]:
    arguments = await resolve(context.guild, inputs, data)
    for name in inputs.injected:
        arguments[name] = context
    return arguments


@dataclass
class Job[C: BaseModel, **P]:
    """A decorated job, which `@plugin.job` returns. Its parameters, after the context, are its payload.

    - `func` is the decorated function, and `name` the job's name within the plugin.
    - `inputs` is the payload's model, read from the function's signature.
    """

    func: Callable[Concatenate[Context[C], P], Awaitable[None]]
    name: str
    inputs: Inputs

    def bind(self, *args: P.args, **kwargs: P.kwargs) -> Bound:
        """The job with its arguments fixed, for `tx.schedule` and `tx.unschedule`. Its key is the job's name and
        arguments, so scheduling the same bound job again moves the pending one."""
        if args:
            raise TypeError(f"{self.name}.bind takes its arguments by name")
        payload = self.inputs.model.model_validate(kwargs).model_dump(mode="json")
        return Bound(self.name, payload, f"{self.name}:{json.dumps(payload, sort_keys=True)}")

    async def _handle(self, job: JobContext) -> None:
        guild = job.client.get_guild(job.guild_id) if job.guild_id is not None else None
        if guild is None:
            raise ActionError("The bot is no longer in this job's server.")
        actor = Actor(job.started_by or SYSTEM, "job")
        context = _Context(guild_view(guild), actor, job.config, lambda: job.db, job.report)
        data = self.inputs.model.model_validate(dict(job.payload))
        func: Callable[..., Awaitable[None]] = self.func
        await func(**await _arguments(self.inputs, context, data))


class Plugin(Generic[Cfg]):
    """A plugin: its id, its per-server config, and the actions and jobs decorated with it.

    The version comes from the plugin's package, and migrations from a `migrations/` directory beside it.
    """

    # Python 3.12 has no syntax for a type parameter's default, so this uses Generic and typing_extensions.
    def __init__(self, id: str, *, config: type[Cfg] = EmptyConfig, migrations: Path | None = None) -> None:
        self.id = id
        self.config = config
        self._migrations = migrations
        self._module: str | None = None
        self._version: str | None = None
        self.actions: dict[str, Action[Cfg, ..., Any]] = {}
        self.jobs: dict[str, Job[Cfg, ...]] = {}

    def action[**P, R](
        self,
        *,
        risk: Risk = WRITE,
        needs: Permission | tuple[Permission, ...] = (),
        name: str | None = None,
        reply: Literal["private", "public"] = "private",
    ) -> Callable[[Callable[Concatenate[Context[Cfg], P], Awaitable[R]]], Action[Cfg, P, R]]:
        """Make a function an action: a slash command, an MCP tool and a service route at once (D1).

        Its name is the function's, without a trailing underscore, unless `name` says otherwise. Its docstring's
        first line is the summary, and its `Args:` section describes each input.
        """

        def register(func: Callable[Concatenate[Context[Cfg], P], Awaitable[R]]) -> Action[Cfg, P, R]:
            action_name = f"{self.id}.{name or func.__name__.removesuffix('_')}"
            self._check_context(func, action_name)
            inputs = read_inputs(func, action_name, injected={Context: "context"})
            built = Action(
                func, action_name, risk, _permissions(needs), reply, inputs, read_output(func, action_name)
            )
            self.actions[action_name] = built
            self._module = self._module or func.__module__
            return built

        return register

    def job[**P](self, func: Callable[Concatenate[Context[Cfg], P], Awaitable[None]]) -> Job[Cfg, P]:
        """Make a function one of the plugin's jobs. Its parameters, after the context, are its payload."""
        job_name = func.__name__
        self._check_context(func, f"{self.id}.{job_name}")
        inputs = read_inputs(func, f"{self.id}.{job_name}", injected={Context: "context"}, needs_docs=False)
        built = Job(func, job_name, inputs)
        self.jobs[job_name] = built
        self._module = self._module or func.__module__
        return built

    def _check_context(self, func: Callable[..., Any], name: str) -> None:
        params = list(inspect.signature(func).parameters.values())
        hint = unalias(params[0].annotation) if params else None
        configured = get_args(hint)
        wanted = configured[0] if configured else Any
        if wanted is not Any and isinstance(wanted, type) and wanted is not self.config:
            raise SignatureError(
                f"{where(func)}: {name} takes Context[{wanted.__name__}], but the plugin's config is "
                f"{self.config.__name__}. Use the plugin's Ctx alias."
            )

    def locate(self, module: str, version: str | None) -> None:
        """Called by the loader with the entry point's module and its distribution's version."""
        self._module = module
        self._version = version

    @property
    def manifest(self) -> Manifest:
        """What the core needs before loading the plugin, worked out from its package."""
        return Manifest(
            self.id, self._version or _version_of(self._module), self.config, self._migrations_dir()
        )

    def _migrations_dir(self) -> Path | None:
        if self._migrations is not None:
            return self._migrations
        module = sys.modules.get(self._module or "")
        file = getattr(module, "__file__", None)
        if file is None:
            return None
        found = Path(file).parent / "migrations"
        return found if found.is_dir() else None

    def setup(self, registrar: Registrar) -> None:
        """Register every decorated action and job with the core."""
        for action in self.actions.values():
            if action.risk is DESTRUCTIVE and action.planner is None:
                raise SignatureError(
                    f"{where(action.func)}: {action.name} is destructive and needs a plan. "
                    f"Decorate a function with @{action.func.__name__}.plan (D21)."
                )
            registrar.action(action.spec())
        for job in self.jobs.values():
            registrar.job(job.name, job._handle)  # pyright: ignore[reportPrivateUsage]


def _version_of(module: str | None) -> str:
    """The version of the installed distribution that holds `module`, or 0.0.0 for code that is not one."""
    top = (module or "").split(".", 1)[0]
    for dist in importlib.metadata.packages_distributions().get(top, []):
        return importlib.metadata.version(dist)
    return "0.0.0"
