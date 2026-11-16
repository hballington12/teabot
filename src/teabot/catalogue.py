"""The plugin hub's catalogue (D51): every listed plugin, with every version its maintainers reviewed.

Each version names the teabot versions it runs on, so a service picks, for each plugin, the newest reviewed version
its own teabot runs. Services on different teabot releases read the same catalogue.
"""

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

import teabot

DEFAULT_HUB = "https://teabot-dev.github.io/plugin-hub/catalogue.json"
HUB_PAGE = "https://teabot-dev.github.io/teabot/hub/"
COMMIT = re.compile(r"[0-9a-f]{40}")
GIT_REQUIREMENT = re.compile(
    r"^(?P<package>teabot-[a-z0-9_-]+)\s*@\s*git\+(?P<repository>\S+?)@(?P<commit>[0-9a-f]{40})$"
)


@dataclass(frozen=True)
class Reviewed:
    """One reviewed version of a plugin: its `commit`, its package `version`, the `teabot` range it runs on, the
    `requirement` that installs it, what it contacts, and the packages it adds beyond teabot's own."""

    commit: str
    version: str
    teabot: str
    requirement: str
    external_connections: str
    dependencies: tuple[str, ...]

    def runs_on(self, teabot_version: str) -> bool:
        """Whether this version's teabot range admits `teabot_version`, development releases included."""
        try:
            return SpecifierSet(self.teabot).contains(Version(teabot_version), prereleases=True)
        except (InvalidSpecifier, InvalidVersion):
            return False


@dataclass(frozen=True)
class Listed:
    """One plugin in the catalogue, with its reviewed versions, newest first."""

    id: str
    package: str
    description: str
    repository: str
    versions: tuple[Reviewed, ...]

    def for_teabot(self, teabot_version: str = teabot.__version__) -> Reviewed | None:
        """The newest reviewed version that runs on `teabot_version`, or None."""
        return next((v for v in self.versions if v.runs_on(teabot_version)), None)

    @property
    def newest(self) -> Reviewed:
        return self.versions[0]


def _reviewed(item: Mapping[str, Any]) -> Reviewed:
    return Reviewed(
        str(item["commit"]),
        str(item.get("version", "")),
        str(item.get("teabot", "")),
        str(item["requirement"]),
        str(item.get("external_connections", "")),
        tuple(str(d) for d in item.get("dependencies", [])),
    )


def parse(data: Mapping[str, Any]) -> dict[str, Listed]:
    """The catalogue's plugins, by id. A catalogue from before versions were listed gives each plugin its one."""
    found: dict[str, Listed] = {}
    for item in data.get("plugins", []):
        versions = tuple(_reviewed(v) for v in item.get("versions", [])) or (_reviewed(item),)
        found[str(item["id"])] = Listed(
            str(item["id"]),
            str(item["package"]),
            str(item.get("description", "")),
            str(item["repository"]),
            versions,
        )
    return found


def fetch(url: str = DEFAULT_HUB, transport: httpx.BaseTransport | None = None) -> dict[str, Listed]:
    """The hub's catalogue at `url`. Raises `httpx.HTTPError` when it cannot be read."""
    with httpx.Client(transport=transport, timeout=15, follow_redirects=True) as client:
        reply = client.get(url)
        reply.raise_for_status()
        return parse(reply.json())


async def fetch_async(
    url: str = DEFAULT_HUB, transport: httpx.AsyncBaseTransport | None = None
) -> dict[str, Listed]:
    """`fetch` for the running bot, which must not block its event loop."""
    async with httpx.AsyncClient(transport=transport, timeout=15, follow_redirects=True) as client:
        reply = await client.get(url)
        reply.raise_for_status()
        return parse(reply.json())


def installed(pyproject: Path) -> dict[str, str]:
    """The plugins an instance installed from git at a commit, as the hub installs them: each one's commit, by
    package. `uv add` writes such a plugin as its name in `dependencies` and its commit in `[tool.uv.sources]`;
    a requirement written out in full, `teabot-x @ git+...@<commit>`, counts too."""
    if not pyproject.exists():
        return {}
    data: dict[str, Any] = tomllib.loads(pyproject.read_text())
    found: dict[str, str] = {}
    for dependency in data.get("project", {}).get("dependencies", []):
        matched = GIT_REQUIREMENT.match(str(dependency).strip())
        if matched is not None:
            found[matched.group("package")] = matched.group("commit")
    sources: dict[str, Any] = data.get("tool", {}).get("uv", {}).get("sources", {})
    for package, source in sources.items():
        if not isinstance(source, dict) or not str(package).startswith("teabot-"):
            continue
        entry = cast(dict[str, Any], source)
        rev = str(entry.get("rev", ""))
        if entry.get("git") and COMMIT.fullmatch(rev):
            found[str(package)] = rev
    return found


@dataclass(frozen=True)
class Change:
    """One step `teabot hub sync` takes: installing `plugin` at `to`, or moving it there from `was`."""

    plugin: Listed
    to: Reviewed
    was: str | None


@dataclass(frozen=True)
class SyncPlan:
    """What a sync would do: the `changes`, the installed plugins the hub no longer lists, and the listed ones no
    reviewed version of which runs on this teabot."""

    changes: tuple[Change, ...]
    delisted: tuple[str, ...]
    too_new: tuple[Listed, ...]


def plan_sync(
    listed: Mapping[str, Listed],
    have: Mapping[str, str],
    *,
    skip: frozenset[str] = frozenset(),
    teabot_version: str = teabot.__version__,
) -> SyncPlan:
    """Every listed plugin, but those in `skip`, at the newest reviewed version this teabot runs."""
    changes: list[Change] = []
    too_new: list[Listed] = []
    for plugin in sorted(listed.values(), key=lambda p: p.id):
        if plugin.id in skip:
            continue
        chosen = plugin.for_teabot(teabot_version)
        if chosen is None:
            too_new.append(plugin)
        elif have.get(plugin.package) != chosen.commit:
            changes.append(Change(plugin, chosen, have.get(plugin.package)))
    packages = {p.package for p in listed.values()}
    delisted = tuple(sorted(package for package in have if package not in packages))
    return SyncPlan(tuple(changes), delisted, tuple(too_new))
