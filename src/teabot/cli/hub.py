"""`teabot hub`: find, install and update plugins from the teabot plugin hub, where maintainers review each one.

The hub publishes a catalogue of the plugins it lists, each at the commit that was reviewed. Installing adds that
exact commit to the instance's `pyproject.toml`, so the bot runs what was reviewed and nothing newer.
"""

import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import httpx
import typer

app = typer.Typer(
    name="hub", help="Find and install reviewed plugins from the teabot plugin hub.", no_args_is_help=True
)

DEFAULT_HUB = "https://teabot-dev.github.io/plugin-hub/catalogue.json"
HUB_PAGE = "https://teabot-dev.github.io/plugin-hub/"
GIT_REQUIREMENT = re.compile(
    r"^(?P<package>teabot-[a-z0-9_-]+)\s*@\s*git\+(?P<repository>\S+?)@(?P<commit>[0-9a-f]{40})$"
)
Hub = Annotated[str, typer.Option(envvar="TEABOT_HUB_URL", help="The hub's catalogue.")]


@dataclass(frozen=True)
class Listed:
    """One plugin in the hub's catalogue."""

    id: str
    package: str
    version: str
    description: str
    repository: str
    commit: str
    requirement: str
    external_connections: str
    dependencies: tuple[str, ...]
    teabot: str


def catalogue(url: str, transport: httpx.BaseTransport | None = None) -> dict[str, Listed]:
    """The hub's plugins, by id."""
    with httpx.Client(transport=transport, timeout=15, follow_redirects=True) as client:
        reply = client.get(url)
        reply.raise_for_status()
        data: dict[str, Any] = reply.json()
    found: dict[str, Listed] = {}
    for item in data.get("plugins", []):
        found[str(item["id"])] = Listed(
            str(item["id"]),
            str(item["package"]),
            str(item.get("version", "")),
            str(item.get("description", "")),
            str(item["repository"]),
            str(item["commit"]),
            str(item["requirement"]),
            str(item.get("external_connections", "")),
            tuple(str(d) for d in item.get("dependencies", [])),
            str(item.get("teabot", "")),
        )
    return found


def _load(url: str) -> dict[str, Listed]:
    try:
        return catalogue(url)
    except httpx.HTTPError as exc:
        typer.echo(f"Could not read the hub's catalogue at {url}: {exc}", err=True)
        raise typer.Exit(1) from None


def _one(url: str, plugin_id: str) -> Listed:
    found = _load(url).get(plugin_id)
    if found is None:
        typer.echo(
            f"The hub lists no plugin called {plugin_id}. See `teabot hub search`, or {HUB_PAGE}", err=True
        )
        raise typer.Exit(1)
    return found


def install_line(plugin: Listed) -> str:
    """The line that installs the plugin without uv on the machine."""
    return f'docker compose run --rm uv add "{plugin.requirement}"'


def installed(pyproject: Path) -> dict[str, str]:
    """The plugins an instance installed from git at a commit, as the hub installs them: each one's commit, by
    package."""
    if not pyproject.exists():
        return {}
    project: dict[str, Any] = tomllib.loads(pyproject.read_text()).get("project", {})
    found: dict[str, str] = {}
    for dependency in project.get("dependencies", []):
        matched = GIT_REQUIREMENT.match(str(dependency).strip())
        if matched is not None:
            found[matched.group("package")] = matched.group("commit")
    return found


@app.command("search")
def search(
    words: Annotated[
        list[str] | None, typer.Argument(help="Words to look for; all plugins without any.")
    ] = None,
    hub: Hub = DEFAULT_HUB,
) -> None:
    """List the hub's plugins, or those whose id or description holds every word given."""
    wanted = [w.lower() for w in words or []]
    shown = [p for p in _load(hub).values() if all(w in f"{p.id} {p.description}".lower() for w in wanted)]
    for plugin in sorted(shown, key=lambda p: p.id):
        typer.echo(f"{plugin.id:<20} {plugin.version:<10} {plugin.description}")
    if not shown:
        typer.echo("No plugins match.")


@app.command("show")
def show(plugin_id: Annotated[str, typer.Argument(help="The plugin's id.")], hub: Hub = DEFAULT_HUB) -> None:
    """Show one plugin: what it does, what it contacts, what it depends on, and how to install it."""
    plugin = _one(hub, plugin_id)
    typer.echo(f"{plugin.id} {plugin.version}: {plugin.description}")
    typer.echo(f"  source        {plugin.repository} at {plugin.commit[:12]}")
    typer.echo(f"  contacts      {plugin.external_connections or 'none given'}")
    typer.echo(f"  depends on    teabot {plugin.teabot}; {', '.join(plugin.dependencies) or 'nothing else'}")
    typer.echo(f"  install       uv run teabot hub add {plugin.id}")
    typer.echo(f"  without uv    {install_line(plugin)}")


@app.command("add")
def add(plugin_id: Annotated[str, typer.Argument(help="The plugin's id.")], hub: Hub = DEFAULT_HUB) -> None:
    """Install a plugin at its reviewed commit, or move an installed one to the newest reviewed commit."""
    plugin = _one(hub, plugin_id)
    typer.echo(f"{plugin.id} contacts: {plugin.external_connections or 'none given'}")
    uv = shutil.which("uv")
    if uv is None or not Path("pyproject.toml").exists():
        typer.echo("Run this in your instance's folder to install it:")
        typer.echo(f"  {install_line(plugin)}")
        raise typer.Exit(0 if uv is None else 1)
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    done = subprocess.run([uv, "add", "--no-sync", plugin.requirement], env=env, check=False)
    if done.returncode != 0:
        raise typer.Exit(done.returncode)
    typer.echo(f"Added {plugin.package} at {plugin.commit[:12]}. Commit pyproject.toml and uv.lock, then:")
    typer.echo("  docker compose up -d --build")
    typer.echo(f"and in each server that wants it, /plugins enable plugin:{plugin.id}")


@app.command("outdated")
def outdated(hub: Hub = DEFAULT_HUB) -> None:
    """List the installed hub plugins whose reviewed commit is newer, or that the hub no longer lists."""
    have = installed(Path("pyproject.toml"))
    if not have:
        typer.echo("No plugins from the hub are installed here.")
        return
    listed = {p.package: p for p in _load(hub).values()}
    for package, commit in sorted(have.items()):
        plugin = listed.get(package)
        if plugin is None:
            typer.echo(f"{package:<26} no longer listed on the hub; read why at {HUB_PAGE}")
        elif plugin.commit != commit:
            typer.echo(
                f"{package:<26} {commit[:12]} -> {plugin.commit[:12]}: uv run teabot hub add {plugin.id}"
            )
        else:
            typer.echo(f"{package:<26} up to date")
