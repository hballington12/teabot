"""The plugin loader (D4, D13, D14, D46).

Candidates come from `teapot.plugins` entry points, or from a list in tests. A plugin is loaded only when its
id is unique, it is not disabled, no purge holds its lock, its migrations apply and its `setup` succeeds. Every
other plugin gets a status with its reason, and everything else still loads.
"""

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Literal, Protocol

from teapot.db.migrate import MigrationReport, PluginMigrations
from teapot.sdk import ActionSpec, JobHandler, Plugin

log = logging.getLogger(__name__)

GROUP = "teapot.plugins"

type Reason = Literal["blocked", "failed", "duplicate_id", "uninstalled"]


@dataclass(frozen=True)
class PluginStatus:
    loaded: bool
    reason: Reason | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.loaded == (self.reason is not None):
            raise ValueError("a loaded plugin has no reason, and a plugin that is not loaded has one")


LOADED = PluginStatus(loaded=True)


@dataclass(frozen=True)
class Candidate:
    """One plugin offered to the loader. `plugin` is None when it could not even be imported."""

    name: str
    origin: str
    plugin: Plugin | None
    error: str | None = None


@dataclass
class Loaded:
    plugin: Plugin
    actions: dict[str, ActionSpec[Any, Any]] = field(default_factory=dict[str, ActionSpec[Any, Any]])
    jobs: dict[str, JobHandler] = field(default_factory=dict[str, JobHandler])


@dataclass
class LoadReport:
    loaded: dict[str, Loaded] = field(default_factory=dict[str, Loaded])
    statuses: dict[str, PluginStatus] = field(default_factory=dict[str, PluginStatus])

    def labels(self) -> dict[str, str]:
        """Each plugin's status as `/healthz` and the process row show it: `loaded`, or the reason."""
        return {p: "loaded" if s.loaded else str(s.reason) for p, s in self.statuses.items()}

    def fail(self, plugin_id: str, reason: Reason, error: str | None = None) -> None:
        self.statuses[plugin_id] = PluginStatus(loaded=False, reason=reason, error=error)
        if reason != "blocked":
            log.error("plugin not loaded", extra={"plugin": plugin_id, "reason": reason, "error": error})


class EntryPointLike(Protocol):
    """An entry point. Its `dist`, when there is one, names the package that declared it."""

    @property
    def name(self) -> str: ...

    def load(self) -> Any: ...


class PluginLocks(Protocol):
    async def take_plugins(self, plugin_ids: Iterable[str]) -> list[str]: ...

    async def release_plugin(self, plugin_id: str) -> None: ...


type Migrator = Callable[[Sequence[PluginMigrations]], Awaitable[MigrationReport]]


def _is_plugin(obj: object) -> bool:
    return hasattr(obj, "manifest") and callable(getattr(obj, "setup", None))


def _candidate(ep: EntryPointLike) -> Candidate:
    dist = getattr(ep, "dist", None)
    origin: str = dist.name if dist is not None else ep.name
    try:
        obj = ep.load()
    except Exception as exc:
        return Candidate(ep.name, origin, None, f"import failed: {exc!r}")
    if not _is_plugin(obj):
        return Candidate(ep.name, origin, None, f"{ep.name} is not a teapot plugin")
    return Candidate(obj.manifest.id, origin, obj)


type Finder = Callable[[str], Iterable[EntryPointLike]]


def installed(group: str) -> Iterable[EntryPointLike]:
    """The entry points of the installed packages in `group`."""
    return entry_points(group=group)


def discover(find: Finder = installed) -> list[Candidate]:
    """Every `teapot.plugins` entry point, loaded or with the reason it could not be."""
    return [_candidate(ep) for ep in find(GROUP)]


def from_plugins(plugins: Iterable[Plugin]) -> list[Candidate]:
    """Candidates from plugin objects, for tests that skip packaging."""
    return [Candidate(p.manifest.id, f"{type(p).__module__}.{type(p).__qualname__}", p) for p in plugins]


class _Registrar:
    """Collects one plugin's registrations, so a failed setup leaves nothing behind."""

    def __init__(self, plugin_id: str) -> None:
        self.plugin_id = plugin_id
        self.actions: dict[str, ActionSpec[Any, Any]] = {}
        self.jobs: dict[str, JobHandler] = {}

    def action(self, spec: ActionSpec[Any, Any]) -> None:
        if spec.plugin_id != self.plugin_id:
            raise ValueError(f"{self.plugin_id} registered {spec.name}, outside its own namespace")
        if spec.name in self.actions:
            raise ValueError(f"{spec.name} registered twice")
        self.actions[spec.name] = spec

    def job(self, name: str, handler: JobHandler) -> None:
        if name in self.jobs:
            raise ValueError(f"job {name} registered twice")
        self.jobs[name] = handler


def _unique(candidates: Sequence[Candidate], report: LoadReport) -> dict[str, Plugin]:
    """Plugins whose id only one candidate declares. Unimportable and duplicated ones are reported."""
    by_id: defaultdict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        if candidate.plugin is None:
            report.fail(candidate.name, "failed", candidate.error)
        else:
            by_id[candidate.name].append(candidate)
    unique: dict[str, Plugin] = {}
    for plugin_id, group in by_id.items():
        if len(group) > 1:
            report.fail(plugin_id, "duplicate_id", "declared by " + " and ".join(c.origin for c in group))
        else:
            unique[plugin_id] = group[0].plugin  # pyright: ignore[reportArgumentType]
    return unique


async def _lock(plugins: dict[str, Plugin], locks: PluginLocks | None, report: LoadReport) -> None:
    if locks is None:
        return
    for plugin_id in await locks.take_plugins(plugins):
        report.fail(plugin_id, "failed", "a purge of this plugin is running")
        del plugins[plugin_id]


async def _migrate(plugins: dict[str, Plugin], migrator: Migrator, report: LoadReport) -> list[str]:
    result = await migrator([PluginMigrations(p, plugins[p].manifest.migrations) for p in plugins])
    for plugin_id, error in result.failed.items():
        report.fail(plugin_id, "failed", error)
        del plugins[plugin_id]
    return list(result.failed)


def _setup(plugin_id: str, plugin: Plugin, report: LoadReport) -> bool:
    registrar = _Registrar(plugin_id)
    try:
        plugin.setup(registrar)
    except Exception as exc:
        report.fail(plugin_id, "failed", f"setup failed: {exc!r}")
        return False
    report.loaded[plugin_id] = Loaded(plugin, registrar.actions, registrar.jobs)
    report.statuses[plugin_id] = LOADED
    return True


async def load(
    candidates: Sequence[Candidate],
    *,
    disabled: Collection[str],
    migrate_with: Migrator,
    lock: PluginLocks | None = None,
) -> LoadReport:
    report = LoadReport()
    plugins = _unique(candidates, report)
    for plugin_id in [p for p in plugins if p in disabled]:
        report.fail(plugin_id, "blocked")
        del plugins[plugin_id]
    await _lock(plugins, lock, report)
    unlock = await _migrate(plugins, migrate_with, report)
    unlock += [p for p, plugin in list(plugins.items()) if not _setup(p, plugin, report)]
    if lock is not None:
        for plugin_id in unlock:
            await lock.release_plugin(plugin_id)
    return report
