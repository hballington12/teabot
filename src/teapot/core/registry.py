"""The action registry and its one call path (D1, D2, D18, D19, D24).

Every front door calls `Registry.invoke`. In order: resolve the server, check the plugin is enabled there,
validate the input, check the member's live permissions, audit, run, and record the outcome. A refusal after
the action is known is audited once with the outcome `refused`. Token checks (D17, D20) and destructive plans
(D21) slot in here in milestones 4 and 6.
"""

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, Literal, Protocol

import discord
from pydantic import BaseModel, ValidationError

from teapot.core.config import ConfigError, ConfigStore
from teapot.core.loader import Loaded
from teapot.db.pool import GuildPluginDatabase, Pools
from teapot.sdk import ActionError, ActionSpec, Actor, Risk

log = logging.getLogger(__name__)

type RefusalCode = Literal[
    "unknown_action", "not_in_guild", "plugin_not_enabled", "config_invalid", "invalid_input", "forbidden"
]

ENABLED = "SELECT enabled FROM core.guild_plugins WHERE guild_id = $1 AND plugin_id = $2"


class Refused(Exception):
    """The call was not allowed to run. `code` says why; `message` is safe to show the caller."""

    def __init__(self, code: RefusalCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class ActionFailed(Exception):
    """The action ran and raised. The audit row holds the error. `public_message` is set when the action
    raised `ActionError`, whose message is meant for the member."""

    def __init__(self, error: str, public_message: str | None = None) -> None:
        super().__init__(error)
        self.public_message = public_message


@dataclass(frozen=True)
class Call:
    action: str
    guild_id: int
    actor: Actor
    raw_input: Mapping[str, Any]


@dataclass(frozen=True)
class CallRecord:
    """What the audit log records about one call (D24)."""

    action: str
    guild_id: int
    actor: Actor
    input: Mapping[str, Any]
    risk: Risk


class Audit(Protocol):
    async def started(self, call: CallRecord) -> int: ...

    async def finished(self, audit_id: int, outcome: str, error: str | None) -> None: ...

    async def single(self, call: CallRecord, outcome: str, error: str | None) -> None: ...


class Member(Protocol):
    @property
    def guild_permissions(self) -> discord.Permissions: ...


class Guild(Protocol):
    @property
    def id(self) -> int: ...

    def get_member(self, user_id: int, /) -> Member | None: ...

    async def fetch_member(self, user_id: int, /) -> Member: ...


class GuildSource(Protocol):
    def get_guild(self, guild_id: int, /) -> Guild | None: ...


@dataclass(frozen=True)
class PluginActionContext:
    """The `ActionContext` one call receives, for one server (D2). The plugin's database is opened on first
    use, so a built-in action, which works through core services, never needs a plugin schema."""

    guild: Any
    actor: Actor
    config: BaseModel
    open_db: Callable[[], GuildPluginDatabase] | None

    @property
    def db(self) -> GuildPluginDatabase:
        if self.open_db is None:
            raise RuntimeError("built-in actions work through core services, not ctx.db")
        return self.open_db()

    @property
    def queue(self) -> GuildPluginDatabase:
        return self.db


@dataclass(frozen=True)
class ActionSource:
    """What the registry needs from one plugin: its config model, its actions, and how it is enabled.

    A built-in plugin is always enabled and has no schema; an installed one is enabled per server and acts
    as its own role in its own schema (D9).
    """

    config: type[BaseModel]
    actions: Mapping[str, ActionSpec[Any, Any]]
    builtin: bool = False


def sources_from(loaded: Mapping[str, Loaded]) -> dict[str, ActionSource]:
    return {plugin_id: ActionSource(p.plugin.manifest.config, p.actions) for plugin_id, p in loaded.items()}


class Registry:
    def __init__(
        self,
        sources: Mapping[str, ActionSource],
        *,
        pools: Pools,
        config: ConfigStore,
        client: GuildSource,
        audit: Audit,
    ) -> None:
        self.sources = sources
        self.pools = pools
        self.config = config
        self.client = client
        self.audit = audit
        self.actions: dict[str, ActionSpec[Any, Any]] = {
            name: spec for source in sources.values() for name, spec in source.actions.items()
        }

    async def invoke(self, call: Call) -> BaseModel:
        spec = self.actions.get(call.action)
        if spec is None:
            raise Refused("unknown_action", f"there is no action {call.action}")
        guild = self.client.get_guild(call.guild_id)
        if guild is None:
            raise Refused("not_in_guild", "the bot is not in that server")
        record = CallRecord(call.action, call.guild_id, call.actor, call.raw_input, spec.risk)
        try:
            ctx, data = await self._prepare(spec, call, guild)
        except Refused as refusal:
            await self.audit.single(record, "refused", refusal.code)
            raise
        return await self._run(spec, record, ctx, data)

    async def _prepare(
        self, spec: ActionSpec[Any, Any], call: Call, guild: Guild
    ) -> tuple[PluginActionContext, BaseModel]:
        plugin_id = spec.plugin_id
        source = self.sources[plugin_id]
        if not source.builtin and not await self.pools.core_db().fetchval(ENABLED, call.guild_id, plugin_id):
            raise Refused("plugin_not_enabled", f"{plugin_id} is not enabled in this server")
        try:
            config = await self.config.load(call.guild_id, plugin_id, source.config)
        except ConfigError as exc:
            raise Refused("config_invalid", str(exc)) from exc
        try:
            data = spec.input.model_validate(call.raw_input)
        except ValidationError as exc:
            raise Refused("invalid_input", str(exc)) from exc
        await self._check_permission(spec, call, guild)
        open_db = None if source.builtin else partial(self.pools.guild_plugin_db, plugin_id, call.guild_id)
        return PluginActionContext(guild, call.actor, config, open_db), data

    async def _check_permission(self, spec: ActionSpec[Any, Any], call: Call, guild: Guild) -> None:
        """The member's current permissions, from the cache or over REST (D18), against the action's (D19)."""
        member = guild.get_member(call.actor.user_id)
        if member is None:
            try:
                member = await guild.fetch_member(call.actor.user_id)
            except discord.NotFound:
                raise Refused("forbidden", "you are not a member of this server") from None
        if not member.guild_permissions >= spec.default_permissions:
            raise Refused("forbidden", f"{spec.name} needs permissions you do not have")

    async def _run(
        self, spec: ActionSpec[Any, Any], record: CallRecord, ctx: PluginActionContext, data: BaseModel
    ) -> BaseModel:
        audit_id = await self.audit.started(record) if spec.risk > Risk.READ else None
        try:
            output = await spec.run(ctx, data)
        except ActionError as exc:
            await self._record(spec, record, audit_id, "error", str(exc))
            raise ActionFailed(repr(exc), public_message=str(exc)) from exc
        except Exception as exc:
            await self._record(spec, record, audit_id, "error", repr(exc))
            raise ActionFailed(repr(exc)) from exc
        await self._record(spec, record, audit_id, "ok", None)
        return output

    async def _record(
        self,
        spec: ActionSpec[Any, Any],
        record: CallRecord,
        audit_id: int | None,
        outcome: str,
        error: str | None,
    ) -> None:
        if audit_id is None:
            await self.audit.single(record, outcome, error)
        else:
            await self.audit.finished(audit_id, outcome, error)
