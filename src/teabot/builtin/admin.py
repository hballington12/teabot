"""The core admin plugin (D3, D10, D24, plan): always enabled, with no schema, Manage Server by default.

Its actions go through the one call path like any plugin's, so they are permission-checked and audited, but
they work on the core's tables through core services, not through `ctx.db`.
"""

import json
from collections.abc import Awaitable, Callable, Mapping, MutableMapping
from typing import Any

import discord
from pydantic import BaseModel, Field, ValidationError

from teabot.builtin.config import AdminConfig
from teabot.builtin.suggest import matching
from teabot.core.config import ConfigStore
from teabot.core.registry import ActionSource
from teabot.db.pool import Database
from teabot.sdk import ActionContext, ActionError, ActionSpec, ChannelRef, Choice, Risk, Surface

MANAGE_SERVER = discord.Permissions(manage_guild=True)
ADMIN = "admin"

STATES = "SELECT plugin_id, enabled FROM core.guild_plugins WHERE guild_id = $1 AND plugin_id <> 'admin'"
WAS_ENABLED = (
    "SELECT coalesce((SELECT enabled FROM core.guild_plugins WHERE guild_id = $1 AND plugin_id = $2), false)"
)
SET_ENABLED = """
INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled, updated_by) VALUES ($1, $2, $3, $4)
ON CONFLICT (guild_id, plugin_id) DO UPDATE
SET enabled = EXCLUDED.enabled, updated_by = EXCLUDED.updated_by, updated_at = now()
"""
RECENT = """
SELECT id, action, outcome, user_id FROM core.audit_log WHERE guild_id = $1 ORDER BY id DESC LIMIT 10
"""


class NoInput(BaseModel):
    pass


class PluginChoice(BaseModel):
    plugin: str = Field(description="The plugin's id, as /plugins list shows it")


class ConfigChange(BaseModel):
    plugin: str = Field(description="The plugin's id, as /plugins list shows it")
    setting: str | None = Field(default=None, description="A setting to change; leave out to see them all")
    value: str | None = Field(default=None, description="The setting's new value")


class LogChannel(BaseModel):
    channel: ChannelRef = Field(description="Where audit posts go")


class PluginState(BaseModel):
    plugin: str
    state: str


class PluginStates(BaseModel):
    plugins: list[PluginState]


class Toggled(BaseModel):
    plugin: str
    enabled: bool


class Settings(BaseModel):
    plugin: str
    settings: dict[str, Any]


class LogChannelSet(BaseModel):
    channel_id: int


class AuditEntry(BaseModel):
    id: int
    action: str
    outcome: str
    user_id: int


class Recent(BaseModel):
    entries: list[AuditEntry]


def _parse(value: str) -> Any:
    """A setting's value as JSON when it is JSON (numbers, true, false), else as the text typed."""
    try:
        return json.loads(value)
    except ValueError:
        return value


async def _nothing(_guild_id: int) -> None:
    return None


async def _nothing_enabled(_guild_id: int, _plugin_id: str, _user_id: int) -> None:
    return None


class Admin:
    """The admin plugin's actions over core services. `statuses` maps each known plugin to `loaded` or the
    reason it is not; `configs` holds the config model of each loaded plugin."""

    def __init__(
        self,
        db: Database,
        *,
        statuses: MutableMapping[str, str],
        configs: Mapping[str, type[BaseModel]],
        on_change: Callable[[int], Awaitable[None]] = _nothing,
        on_enabled: Callable[[int, str, int], Awaitable[None]] = _nothing_enabled,
    ) -> None:
        self.db = db
        self.store = ConfigStore(db)
        self.statuses = statuses
        self.configs = configs
        self.on_change = on_change
        self.on_enabled = on_enabled

    def _known(self, plugin: str) -> str:
        if plugin not in self.statuses or plugin == ADMIN:
            raise ActionError(f"There is no installed plugin called {plugin}.")
        return self.statuses[plugin]

    async def list_plugins(self, ctx: ActionContext, _data: NoInput) -> PluginStates:
        enabled = {r["plugin_id"]: r["enabled"] for r in await self.db.fetch(STATES, ctx.guild.id)}
        known = sorted(set(self.statuses) | set(enabled))
        labels = {p: self.statuses.get(p, "uninstalled") for p in known}
        states = [PluginState(plugin=p, state=state_here(labels[p], enabled.get(p, False))) for p in known]
        return PluginStates(plugins=states)

    async def _set(self, ctx: ActionContext, plugin: str, enabled: bool) -> Toggled:
        was = await self.db.fetchval(WAS_ENABLED, ctx.guild.id, plugin)
        await self.db.execute(SET_ENABLED, ctx.guild.id, plugin, enabled, ctx.actor.user_id)
        await self.on_change(ctx.guild.id)
        if enabled and not was:
            await self.on_enabled(ctx.guild.id, plugin, ctx.actor.user_id)
        return Toggled(plugin=plugin, enabled=enabled)

    async def enable(self, ctx: ActionContext, data: PluginChoice) -> Toggled:
        label = self._known(data.plugin)
        if label != "loaded":
            raise ActionError(f"{data.plugin} is not loaded ({label}), so it cannot be enabled.")
        return await self._set(ctx, data.plugin, True)

    async def disable(self, ctx: ActionContext, data: PluginChoice) -> Toggled:
        self._known(data.plugin)
        return await self._set(ctx, data.plugin, False)

    def _model(self, plugin: str) -> type[BaseModel]:
        label = self._known(plugin)
        if label != "loaded":
            raise ActionError(f"{plugin} is not loaded ({label}), so it has no settings to show or change.")
        return self.configs[plugin]

    async def configure(self, ctx: ActionContext, data: ConfigChange) -> Settings:
        """Without a setting, show the plugin's settings here; with a setting and a value, change it."""
        model = self._model(data.plugin)
        current = await self.store.load(ctx.guild.id, data.plugin, model)
        if data.setting is None:
            return Settings(plugin=data.plugin, settings=current.model_dump(mode="json"))
        if data.value is None:
            raise ActionError(f"Give a value for {data.setting}.")
        updated = changed(data.plugin, current, data.setting, data.value)
        await self.store.save(ctx.guild.id, data.plugin, updated, ctx.actor.user_id)
        return Settings(plugin=data.plugin, settings=updated.model_dump(mode="json"))

    async def log_channel(self, ctx: ActionContext, data: LogChannel) -> LogChannelSet:
        await self.store.save(
            ctx.guild.id, ADMIN, AdminConfig(log_channel_id=data.channel), ctx.actor.user_id
        )
        return LogChannelSet(channel_id=data.channel)

    async def recent(self, ctx: ActionContext, _data: NoInput) -> Recent:
        rows = await self.db.fetch(RECENT, ctx.guild.id)
        return Recent(
            entries=[
                AuditEntry(id=r["id"], action=r["action"], outcome=r["outcome"], user_id=r["user_id"])
                for r in rows
            ]
        )

    async def _enabled_here(self, ctx: ActionContext) -> set[str]:
        return {r["plugin_id"] for r in await self.db.fetch(STATES, ctx.guild.id) if r["enabled"]}

    def _loaded(self) -> list[str]:
        return sorted(p for p, label in self.statuses.items() if label == "loaded" and p != ADMIN)

    async def suggest_enable(self, ctx: ActionContext, typed: str) -> list[Choice[str]]:
        """The loaded plugins that are off here."""
        on = await self._enabled_here(ctx)
        return matching((Choice(p, p) for p in self._loaded() if p not in on), typed)

    async def suggest_disable(self, ctx: ActionContext, typed: str) -> list[Choice[str]]:
        """The plugins that are on here."""
        return matching((Choice(p, p) for p in sorted(await self._enabled_here(ctx))), typed)

    async def suggest_plugin(self, ctx: ActionContext, typed: str) -> list[Choice[str]]:
        """The plugins with settings: every loaded one."""
        return matching((Choice(p, p) for p in self._loaded()), typed)

    async def suggest_setting(self, ctx: ActionContext, typed: str) -> list[Choice[str]]:
        """Every loaded plugin's settings, each named with its plugin."""
        choices = (
            Choice(f"{name} ({plugin})", name)
            for plugin in self._loaded()
            for name in self.configs[plugin].model_fields
        )
        return matching(choices, typed)

    def specs(self) -> list[ActionSpec[Any, Any]]:
        table: list[tuple[str, str, type[BaseModel], type[BaseModel], Risk, Any, Any]] = [
            (
                "plugins.list",
                "List the plugins and their state here",
                NoInput,
                PluginStates,
                Risk.READ,
                self.list_plugins,
                render_states,
            ),
            (
                "plugins.enable",
                "Enable a plugin here",
                PluginChoice,
                Toggled,
                Risk.WRITE,
                self.enable,
                render_toggled,
            ),
            (
                "plugins.disable",
                "Disable a plugin here",
                PluginChoice,
                Toggled,
                Risk.WRITE,
                self.disable,
                render_toggled,
            ),
            (
                "plugins.config",
                "Show or change a plugin's settings here",
                ConfigChange,
                Settings,
                Risk.WRITE,
                self.configure,
                render_settings,
            ),
            (
                "audit.channel",
                "Set where audit posts go",
                LogChannel,
                LogChannelSet,
                Risk.WRITE,
                self.log_channel,
                render_log_channel,
            ),
            (
                "audit.recent",
                "Show the latest audited changes here",
                NoInput,
                Recent,
                Risk.READ,
                self.recent,
                render_recent,
            ),
        ]
        suggest: dict[str, dict[str, Any]] = {
            "plugins.enable": {"plugin": self.suggest_enable},
            "plugins.disable": {"plugin": self.suggest_disable},
            "plugins.config": {"plugin": self.suggest_plugin, "setting": self.suggest_setting},
        }
        return [
            ActionSpec(
                name,
                summary,
                inp,
                out,
                risk,
                run,
                default_permissions=MANAGE_SERVER,
                surfaces=Surface.SLASH | Surface.WEB,
                render=render,
                suggest=suggest.get(name, {}),
            )
            for name, summary, inp, out, risk, run, render in table
        ]

    def sources(self) -> dict[str, ActionSource]:
        """One built-in source per command group, so `/plugins` and `/audit` are each a command (D32)."""
        groups: dict[str, dict[str, ActionSpec[Any, Any]]] = {}
        for spec in self.specs():
            groups.setdefault(spec.plugin_id, {})[spec.name] = spec
        return {group: ActionSource(AdminConfig, actions, builtin=True) for group, actions in groups.items()}


def changed(plugin: str, current: BaseModel, setting: str, value: str) -> BaseModel:
    """`current` with one setting changed, validated through the plugin's own model (D10)."""
    model = type(current)
    if setting not in model.model_fields:
        names = ", ".join(model.model_fields)
        raise ActionError(f"{plugin} has no setting {setting}. Its settings are: {names}.")
    try:
        return model.model_validate(current.model_dump(mode="json") | {setting: _parse(value)})
    except ValidationError as exc:
        raise ActionError(f"That value does not fit {setting}: {exc.errors()[0]['msg']}.") from None


def state_here(label: str, enabled: bool) -> str:
    """A plugin's state in one server: enabled or disabled when loaded, else why it is not loaded."""
    if label != "loaded":
        return f"not loaded ({label})"
    return "enabled" if enabled else "disabled"


def render_states(out: PluginStates) -> str:
    return "\n".join(f"`{p.plugin}` {p.state}" for p in out.plugins) or "No plugins are installed."


def render_toggled(out: Toggled) -> str:
    return f"`{out.plugin}` is now {'enabled' if out.enabled else 'disabled'} here."


def render_settings(out: Settings) -> str:
    return f"`{out.plugin}` settings:\n```json\n{json.dumps(out.settings, indent=2)}\n```"


def render_log_channel(out: LogChannelSet) -> str:
    return f"Audit posts now go to <#{out.channel_id}>."


def render_recent(out: Recent) -> str:
    lines = [f"`#{e.id}` {e.action} {e.outcome} by <@{e.user_id}>" for e in out.entries]
    return "\n".join(lines) or "Nothing has been audited here yet."
