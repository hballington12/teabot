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
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Concatenate, Generic, Literal, Protocol, cast, get_args, overload

import discord
from pydantic import BaseModel
from typing_extensions import TypeVar

from teabot.sdk import _clock as clock
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
from teabot.sdk.actions import (
    ACTION_TIMEOUT,
    MENU_NAME_MAX,
    SYSTEM,
    ActionContext,
    ActionError,
    ActionSpec,
    Actor,
    Choice,
    Menu,
    Risk,
    Surface,
)
from teabot.sdk.components import BoundAction
from teabot.sdk.db import Bound, Db
from teabot.sdk.guild import (
    Attachment,
    Guild,
    Member,
    Reaction,
    ReceivedMessage,
    RoleChange,
    User,
    VoiceChange,
    VoiceChannel,
)
from teabot.sdk.http import Http
from teabot.sdk.permissions import Permission
from teabot.sdk.plans import Diff
from teabot.sdk.plugin import EmptyConfig, EventName, JobContext, JobHandler, Manifest, Registrar
from teabot.sdk.settings import InstanceSettings
from teabot.sdk.store import Store
from teabot.sdk.voice import Voice

READ = Risk.READ
WRITE = Risk.WRITE
DESTRUCTIVE = Risk.DESTRUCTIVE


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

    @property
    def voice(self) -> Voice:
        """The server's voice connection, which the plugin joins, plays through and leaves (D54)."""
        ...

    async def report(self, progress: Mapping[str, Any], /) -> None:
        """Record how far a long change has got, which `/admin job_status` shows."""
        ...

    @property
    def http(self) -> Http:
        """The shared HTTP client, for the hosts the plugin declares in `Plugin(..., hosts=[...])` (D12)."""
        ...

    def store[M: BaseModel](self, model: type[M], *, kind: str | None = None) -> Store[M]:
        """This server's records of `model`, by key, with no SQL (D10). Not inside a transaction block."""
        ...


type Suggester[C: BaseModel, T: (str, int)] = Callable[[Context[C], str], Awaitable[list[Choice[T]]]]
"""What `@action.autocomplete(...)` decorates: it takes the context and what the member has typed."""

# How often a recurring job may run at most.
MIN_EVERY = timedelta(minutes=1)


@dataclass
class _Context:
    guild: Guild
    actor: Actor
    config: Any
    open_db: Callable[[], Db]
    reporter: Callable[[Mapping[str, Any]], Awaitable[None]]
    open_voice: Callable[[], Voice]
    diff: Diff = field(default_factory=Diff)
    now: datetime = field(default_factory=clock.now)
    plugin_id: str = ""
    hosts: frozenset[str] = frozenset()

    @property
    def db(self) -> Db:
        return self.open_db()

    @property
    def http(self) -> Http:
        return Http(self.plugin_id, self.hosts)

    @property
    def voice(self) -> Voice:
        return self.open_voice()

    def store[M: BaseModel](self, model: type[M], *, kind: str | None = None) -> Store[M]:
        return Store(self.db, self.guild.id, model, kind or model.__name__)

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
    - `surfaces` are the front doors it is offered through.
    - `suggesters` are the functions `.autocomplete` attached, by the option each suggests values for.
    - `hosts` are the hosts its plugin declared, which its `ctx.http` reaches.
    - `menu` is its right-click command, if `menu=` made one.
    - `timeout` is how long a call may take before it is stopped.
    """

    func: Callable[Concatenate[Context[C], P], Awaitable[R]]
    name: str
    risk: Risk
    needs: discord.Permissions
    reply: Literal["private", "public"]
    inputs: Inputs
    output: Output
    planner: Callable[..., Awaitable[Diff]] | None = None
    surfaces: Surface = Surface.ALL
    suggesters: dict[str, Callable[..., Awaitable[list[Choice[Any]]]]] = field(
        default_factory=dict[str, Callable[..., Awaitable[list[Choice[Any]]]]]
    )
    hosts: frozenset[str] = frozenset()
    menu: Menu | None = None
    timeout: timedelta = ACTION_TIMEOUT

    def autocomplete[T: (str, int)](
        self, option: str
    ) -> Callable[
        [Callable[[Context[C], str], Awaitable[list[Choice[T]]]]],
        Callable[[Context[C], str], Awaitable[list[Choice[T]]]],
    ]:
        """Suggest values for one of the action's options as the member types, such as running giveaways for
        `giveaway`. The function receives what has been typed so far, and returns up to 25 `Choice`s. It runs as
        the member, without the audit log, and must answer within Discord's three seconds."""
        if option not in self.inputs.model.model_fields:
            raise SignatureError(f"{self.name} has no option {option} to suggest values for")

        def attach(
            func: Callable[[Context[C], str], Awaitable[list[Choice[T]]]],
        ) -> Callable[[Context[C], str], Awaitable[list[Choice[T]]]]:
            self.suggesters[option] = func
            return func

        return attach

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
            surfaces=self._surfaces(),
            suggest={option: self._suggester(option) for option in self.suggesters},
            menu=self.menu,
            timeout=self.timeout,
        )

    def _surfaces(self) -> Surface:
        """A destructive action's Confirm button is a press, so a command with a plan is pressable too."""
        if self.risk is DESTRUCTIVE and Surface.SLASH in self.surfaces:
            return self.surfaces | Surface.COMPONENT
        return self.surfaces

    def _suggester(self, option: str) -> Callable[[ActionContext, str], Awaitable[list[Choice[Any]]]]:
        func = self.suggesters[option]

        async def suggest(ctx: ActionContext, typed: str) -> list[Choice[Any]]:
            return list(await func(_context_of(ctx, self.name, self.hosts), typed))[:25]

        return suggest

    def bind(self, *args: P.args, **kwargs: P.kwargs) -> BoundAction:
        """The action with its arguments fixed, for a `Button`. A `Role`, `TextChannel` or `Member` argument is kept
        as its ID, and found again when the button is pressed."""
        if args:
            raise TypeError(f"{self.name}.bind takes its arguments by name")
        refs = {r.name for r in self.inputs.resolved}
        raw = {k: _ids(v) if k in refs else v for k, v in kwargs.items()}
        payload = self.inputs.model.model_validate(raw).model_dump(mode="json", exclude_defaults=True)
        return BoundAction(self.name, payload)

    async def _run(self, ctx: ActionContext, data: BaseModel) -> BaseModel:
        context = _context_of(ctx, self.name, self.hosts)
        arguments = await _arguments(self.inputs, context, data)
        func: Callable[..., Awaitable[Any]] = self.func
        return self.output.wrap(await func(**arguments))

    async def _plan(self, ctx: ActionContext, data: BaseModel) -> Diff:
        assert self.planner is not None
        return await self.planner(
            **await _arguments(self.inputs, _context_of(ctx, self.name, self.hosts), data)
        )


def _ids(value: Any) -> Any:
    """A Discord object as its ID, and a list of them as a list of IDs, as a slash command would send them."""
    if isinstance(value, list | tuple):
        return [str(getattr(item, "id", item)) for item in cast(list[Any], value)]
    return str(getattr(value, "id", value)) if value is not None else None


def _reason(action: str, actor: Actor) -> str:
    """What Discord's audit log shows for a change a plugin makes without its own reason."""
    who = "teabot" if actor.user_id == SYSTEM else f"member {actor.user_id}"
    return f"via teabot: {action}, for {who}"


def _menu_of(func: Callable[..., Any], name: str, menu: str, inputs: Inputs) -> Menu:
    """The right-click command `menu=` asks for, from the action's one input."""
    if not 1 <= len(menu) <= MENU_NAME_MAX:
        raise SignatureError(f"{where(func)}: {name}'s menu name is 1 to {MENU_NAME_MAX} characters")
    fields = list(inputs.model.model_fields)
    resolved = {r.name: r.kind for r in inputs.resolved if not r.many}
    if len(fields) != 1:
        raise SignatureError(
            f"{where(func)}: {name} has a menu, so it takes one input, the member or the message"
        )
    (only,) = fields
    if resolved.get(only) is Member:
        return Menu(menu, "user", only)
    if unalias(inputs.model.model_fields[only].annotation) is ReceivedMessage:
        return Menu(menu, "message", only)
    raise SignatureError(f"{where(func)}: {name} has a menu, so its input is a Member or a ReceivedMessage")


def _context_of(ctx: ActionContext, action: str, hosts: frozenset[str]) -> _Context:
    diff = getattr(ctx, "diff", None) or Diff()
    guild = guild_view(ctx.guild, _reason(action, ctx.actor))
    return _Context(
        guild,
        ctx.actor,
        ctx.config,
        lambda: ctx.db,
        ctx.report,
        lambda: ctx.voice,
        diff,
        plugin_id=action.split(".", maxsplit=1)[0],
        hosts=hosts,
    )


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
    - `every` is how often it runs on its own, or None for a job that runs when scheduled.
    - `plugin_id` is its plugin's id, and `hosts` the hosts its plugin declared, which its `ctx.http` reaches.
    - `timeout` is how long a run may take before it is stopped, or None for teabot's fifteen minutes.
    """

    func: Callable[Concatenate[Context[C], P], Awaitable[None]]
    name: str
    inputs: Inputs
    every: timedelta | None = None
    plugin_id: str = ""
    hosts: frozenset[str] = frozenset()
    timeout: timedelta | None = None

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
        context = _Context(
            guild_view(guild, _reason(self.name, actor)),
            actor,
            job.config,
            lambda: job.db,
            job.report,
            lambda: job.voice,
            plugin_id=self.plugin_id,
            hosts=self.hosts,
        )
        data = self.inputs.model.model_validate(dict(job.payload))
        func: Callable[..., Awaitable[None]] = self.func
        await func(**await _arguments(self.inputs, context, data))


class Plugin(Generic[Cfg]):
    """A plugin: its id, its per-server config, and the actions and jobs decorated with it.

    The version comes from the plugin's package, and migrations from a `migrations/` directory beside it.
    `description`, a sentence on what it does, shows in the instance's plugin browser.
    """

    # Python 3.12 has no syntax for a type parameter's default, so this uses Generic and typing_extensions.
    def __init__(
        self,
        id: str,
        *,
        config: type[Cfg] = EmptyConfig,
        migrations: Path | None = None,
        hosts: Iterable[str] = (),
        description: str = "",
    ) -> None:
        self.id = id
        self.description = description
        self.hosts = frozenset(hosts)
        self.config = config
        self._migrations = migrations
        self._module: str | None = None
        self._version: str | None = None
        self.home = _caller_module()
        self.actions: dict[str, Action[Cfg, ..., Any]] = {}
        self.jobs: dict[str, Job[Cfg, ...]] = {}
        self.listeners: dict[EventName, Callable[..., Awaitable[None]]] = {}
        self.settings: list[InstanceSettings[Any]] = []

    def action[**P, R](
        self,
        *,
        risk: Risk = WRITE,
        needs: Permission | tuple[Permission, ...] = (),
        name: str | None = None,
        reply: Literal["private", "public"] = "private",
        surfaces: Surface = Surface.ALL,
        menu: str | None = None,
        timeout: timedelta = ACTION_TIMEOUT,
    ) -> Callable[[Callable[Concatenate[Context[Cfg], P], Awaitable[R]]], Action[Cfg, P, R]]:
        """Make a function an action: a slash command, an MCP tool, a service route, and what a button or select
        menu runs, at once (D1).

        Its name is the function's, without a trailing underscore, unless `name` says otherwise. Its docstring's
        first line is the summary, and its `Args:` section describes each input. `surfaces` narrows where it is
        offered: `Surface.COMPONENT` for an action only its buttons and menus reach.

        `menu="Give a pet"` also makes it a right-click command, named so in Discord's Apps menu, on a member when
        its one input is a `Member`, or on a message when it is a `ReceivedMessage`. An action on a message is not
        a slash command, since no slash command can give one.

        `timeout` is how long a call may take before teabot stops it and tells the member, a minute unless given.
        """

        def register(func: Callable[Concatenate[Context[Cfg], P], Awaitable[R]]) -> Action[Cfg, P, R]:
            action_name = f"{self.id}.{name or func.__name__.removesuffix('_')}"
            self._check_context(func, action_name)
            inputs = read_inputs(func, action_name, injected={Context: "context"})
            found_menu = _menu_of(func, action_name, menu, inputs) if menu is not None else None
            offered = surfaces
            if found_menu is not None:
                offered = surfaces | Surface.MENU
                if found_menu.kind == "message":
                    offered &= ~Surface.SLASH
            built = Action(
                func,
                action_name,
                risk,
                _permissions(needs),
                reply,
                inputs,
                read_output(func, action_name),
                surfaces=offered,
                hosts=self.hosts,
                menu=found_menu,
                timeout=timeout,
            )
            self.actions[action_name] = built
            self._module = self._module or func.__module__
            return built

        return register

    @overload
    def job[**P](self, func: Callable[Concatenate[Context[Cfg], P], Awaitable[None]], /) -> Job[Cfg, P]: ...
    @overload
    def job(
        self,
        func: None = None,
        /,
        *,
        name: str | None = None,
        every: timedelta | None = None,
        timeout: timedelta | None = None,
    ) -> "NamedJob[Cfg]": ...
    def job(
        self,
        func: Any = None,
        /,
        *,
        name: str | None = None,
        every: timedelta | None = None,
        timeout: timedelta | None = None,
    ) -> Any:
        """Make a function one of the plugin's jobs: `@plugin.job`, or `@plugin.job(name="...")` to keep a name
        that jobs already queued were stored under. Its parameters, after the context, are its payload.

        `@plugin.job(every=timedelta(days=1))` runs it on its own, every day, in each server where the plugin
        is enabled. A recurring job takes no parameters after the context.

        `timeout` is how long a run may take before teabot stops it and retries it later, fifteen minutes unless
        given."""
        if func is None:
            return NamedJob(self, name, every, timeout)
        return self.register_job(func, name)

    def register_job[**P](
        self,
        func: Callable[Concatenate[Context[Cfg], P], Awaitable[None]],
        name: str | None = None,
        every: timedelta | None = None,
        timeout: timedelta | None = None,
    ) -> Job[Cfg, P]:
        """Register a job; `@plugin.job` is the usual way to call this."""
        job_name = name or func.__name__
        self._check_context(func, f"{self.id}.{job_name}")
        inputs = read_inputs(func, f"{self.id}.{job_name}", injected={Context: "context"}, needs_docs=False)
        if every is not None:
            if every < MIN_EVERY:
                raise SignatureError(
                    f"{where(func)}: {self.id}.{job_name} runs every {every}; the least is a minute"
                )
            if inputs.model.model_fields:
                raise SignatureError(
                    f"{where(func)}: {self.id}.{job_name} runs on its own, so it takes no parameters after ctx"
                )
        built = Job(func, job_name, inputs, every, self.id, self.hosts, timeout)
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
            self.id,
            self._version or _version_of(self._module),
            self.config,
            self._migrations_dir(),
            self.description,
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

    def instance_settings[M: BaseModel](self, model: type[M]) -> InstanceSettings[M]:
        """Settings for the whole instance, read from `TEABOT_PLUGIN_<ID>_<FIELD>` when the plugin loads. Keep
        what returns at module level, and call its `get()` where the settings are needed."""
        found = InstanceSettings(self.id, model)
        self.settings.append(found)
        return found

    def setup(self, registrar: Registrar) -> None:
        """Register every decorated action and job with the core, once the instance settings are read."""
        for settings in self.settings:
            settings.load()
        for action in self.actions.values():
            if action.risk is DESTRUCTIVE and action.planner is None:
                raise SignatureError(
                    f"{where(action.func)}: {action.name} is destructive and needs a plan. "
                    f"Decorate a function with @{action.func.__name__}.plan (D21)."
                )
            registrar.action(action.spec())
        for job in self.jobs.values():
            registrar.job(job.name, job._handle, job.timeout)  # pyright: ignore[reportPrivateUsage]
            if job.every is not None:
                registrar.recurring(job.name, job.every)
        for event, func in self.listeners.items():
            registrar.event(event, self._listener(event, func))

    def on_member_join(
        self, func: Callable[[Context[Cfg], Member], Awaitable[None]]
    ) -> Callable[[Context[Cfg], Member], Awaitable[None]]:
        """Run `func` when a member joins a server where the plugin is enabled, with the member. It runs as a job,
        so a failure is retried, and a member who has left again by then is skipped."""
        return self._listen("member_join", func)

    def on_member_leave(
        self, func: Callable[[Context[Cfg], User], Awaitable[None]]
    ) -> Callable[[Context[Cfg], User], Awaitable[None]]:
        """Run `func` when a member leaves, or is kicked or banned from, a server where the plugin is enabled, with
        the `User` they were: their ID and username, since they are no longer a member. It runs as a job."""
        return self._listen("member_leave", func)

    def on_message(
        self, func: Callable[[Context[Cfg], ReceivedMessage], Awaitable[None]]
    ) -> Callable[[Context[Cfg], ReceivedMessage], Awaitable[None]]:
        """Run `func` for each message posted in a server where the plugin is enabled. Messages from bots,
        teabot's own among them, are not heard. Its text arrives only with the Message Content intent on. It
        runs as a job, so keep it quick: every message in a busy server queues one."""
        return self._listen("message", func)

    def on_reaction_add(
        self, func: Callable[[Context[Cfg], Reaction], Awaitable[None]]
    ) -> Callable[[Context[Cfg], Reaction], Awaitable[None]]:
        """Run `func` when someone other than a bot adds a reaction to any message, in a server where the
        plugin is enabled. It runs as a job."""
        return self._listen("reaction_add", func)

    def on_reaction_remove(
        self, func: Callable[[Context[Cfg], Reaction], Awaitable[None]]
    ) -> Callable[[Context[Cfg], Reaction], Awaitable[None]]:
        """Run `func` when someone takes a reaction off a message. It runs as a job."""
        return self._listen("reaction_remove", func)

    def on_member_roles(
        self, func: Callable[[Context[Cfg], RoleChange], Awaitable[None]]
    ) -> Callable[[Context[Cfg], RoleChange], Awaitable[None]]:
        """Run `func` when a member's roles change, with the roles added and removed. Discord reports a change
        only for members teabot has seen since it started, such as by a command or a join. It runs as a job."""
        return self._listen("member_roles", func)

    def on_voice(
        self, func: Callable[[Context[Cfg], VoiceChange], Awaitable[None]]
    ) -> Callable[[Context[Cfg], VoiceChange], Awaitable[None]]:
        """Run `func` when a member joins, leaves or moves between voice channels. Muting and deafening are not
        heard. It runs as a job."""
        return self._listen("voice", func)

    def on_enable(
        self, func: Callable[[Context[Cfg]], Awaitable[None]]
    ) -> Callable[[Context[Cfg]], Awaitable[None]]:
        """Run `func` when a server turns the plugin on, such as to create what it needs there. It runs again
        each time the plugin is turned back on, so check what is already there first. It runs as a job."""
        return self._listen("enable", func)

    def on_track_end(
        self, func: Callable[[Context[Cfg], str, str | None], Awaitable[None]]
    ) -> Callable[[Context[Cfg], str, str | None], Awaitable[None]]:
        """Run `func` when audio the plugin played with `ctx.voice.play` runs out or fails, with the `track` it was
        given and the error, or None when it simply ended (D54). Audio the plugin stopped or replaced does not
        count. It runs as a job in the process holding the connection, so it can play the next track."""
        return self._listen("track_end", func)

    def on_voice_resume(
        self, func: Callable[[Context[Cfg], VoiceChannel | None], Awaitable[None]]
    ) -> Callable[[Context[Cfg], VoiceChannel | None], Awaitable[None]]:
        """Run `func` after a restart in each server whose voice channel the plugin held, with that channel, or None
        when it is gone (D54). The restart dropped the connection, so the plugin joins again to carry on, or
        leaves to give the connection up."""
        return self._listen("voice_resume", func)

    def on_voice_alone(
        self, func: Callable[[Context[Cfg], VoiceChannel | None], Awaitable[None]]
    ) -> Callable[[Context[Cfg], VoiceChannel | None], Awaitable[None]]:
        """Run `func` when the last member other than bots leaves the voice channel the plugin holds, with the
        channel (D54). It runs as a job; someone may have come back by then, so check `channel.listener_ids`
        before leaving, or schedule a job of the plugin's own to check after a grace period."""
        return self._listen("voice_alone", func)

    def _listen[F: Callable[..., Awaitable[None]]](self, event: EventName, func: F) -> F:
        if event in self.listeners:
            raise SignatureError(f"{where(func)}: {self.id} already handles {event}")
        self._check_context(func, f"{self.id}.on_{event}")
        self.listeners[event] = func
        self._module = self._module or func.__module__
        return func

    def _listener(self, event: EventName, func: Callable[..., Awaitable[None]]) -> JobHandler:
        name = f"{self.id}.on_{event}"

        async def handle(job: JobContext) -> None:
            guild = job.client.get_guild(job.guild_id) if job.guild_id is not None else None
            if guild is None:
                return
            actor = Actor(SYSTEM, "event")
            context = _Context(
                guild_view(guild, _reason(name, actor)),
                actor,
                job.config,
                lambda: job.db,
                job.report,
                lambda: job.voice,
                plugin_id=self.id,
                hosts=self.hosts,
            )
            if event == "enable":
                await func(context)
                return
            if event == "track_end":
                error = job.payload.get("error")
                await func(context, str(job.payload["track"]), str(error) if error is not None else None)
                return
            if event in ("voice_resume", "voice_alone"):
                await func(context, context.guild.get_voice_channel(int(job.payload["channel_id"])))
                return
            received = await _received(event, context.guild, job.payload)
            if received is not None:
                await func(context, received)

        return handle


def _role_ids(values: Any) -> tuple[int, ...]:
    return tuple(int(v) for v in values or ())


def _id(value: Any) -> int | None:
    return None if value is None else int(value)


async def _received(event: EventName, guild: Guild, payload: Mapping[str, Any]) -> Any:
    """What a handler for `event` receives, from the event's job payload, or None when there is nothing to hand
    it, such as a member who has left since."""
    if event == "message":
        return ReceivedMessage(
            int(payload["message_id"]),
            int(payload["channel_id"]),
            int(payload["author_id"]),
            str(payload["content"]),
            tuple(Attachment(**a) for a in payload.get("attachments", ())),
        )
    if event in ("reaction_add", "reaction_remove"):
        return Reaction(
            int(payload["message_id"]),
            int(payload["channel_id"]),
            int(payload["user_id"]),
            str(payload["emoji"]),
        )
    user_id = int(payload["user_id"])
    if event == "member_leave":
        return User(user_id, str(payload.get("name") or user_id))
    member = await guild.get_member(user_id)
    return None if member is None else _about_member(event, member, payload)


def _about_member(event: EventName, member: Member, payload: Mapping[str, Any]) -> Any:
    """What a handler for an event about a member who is still here receives."""
    if event == "member_roles":
        return RoleChange(member, _role_ids(payload.get("added")), _role_ids(payload.get("removed")))
    if event == "voice":
        return VoiceChange(member, _id(payload.get("left")), _id(payload.get("joined")))
    return member


@dataclass(frozen=True)
class NamedJob[C: BaseModel]:
    """`@plugin.job(name="...", every=...)`: a job decorator with a given name, or one that recurs."""

    plugin: Plugin[C]
    name: str | None
    every: timedelta | None = None
    timeout: timedelta | None = None

    def __call__[**P](self, func: Callable[Concatenate[Context[C], P], Awaitable[None]]) -> Job[C, P]:
        return self.plugin.register_job(func, self.name, self.every, self.timeout)


def _caller_module() -> str:
    """The module that made the plugin, past any `__init__` of a `Plugin` subclass."""
    frame = sys._getframe(2)  # pyright: ignore[reportPrivateUsage]
    while frame.f_back is not None and frame.f_code.co_name == "__init__":
        frame = frame.f_back
    return str(frame.f_globals.get("__name__", ""))


def _version_of(module: str | None) -> str:
    """The version of the installed distribution that holds `module`, or 0.0.0 for code that is not one."""
    top = (module or "").split(".", 1)[0]
    for dist in importlib.metadata.packages_distributions().get(top, []):
        return importlib.metadata.version(dist)
    return "0.0.0"
