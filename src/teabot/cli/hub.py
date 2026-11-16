"""`teabot hub`: find, install and update plugins from the teabot plugin hub, where maintainers review each one.

Each plugin is installed at the newest reviewed version this teabot runs, pinned to its commit in the instance's
`pyproject.toml`, so the bot runs what was reviewed and nothing newer. `sync` does that for every listed plugin.
"""

import os
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated

import httpx
import typer

import teabot
from teabot import catalogue
from teabot.catalogue import DEFAULT_HUB, HUB_PAGE, Listed, Reviewed, installed, plan_sync

app = typer.Typer(
    name="hub", help="Find and install reviewed plugins from the teabot plugin hub.", no_args_is_help=True
)
Hub = Annotated[str, typer.Option(envvar="TEABOT_HUB_URL", help="The hub's catalogue.")]
PYPROJECT = Path("pyproject.toml")


def _load(url: str) -> dict[str, Listed]:
    try:
        return catalogue.fetch(url)
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


def _runnable(plugin: Listed) -> Reviewed:
    chosen = plugin.for_teabot()
    if chosen is None:
        typer.echo(
            f"No reviewed version of {plugin.id} runs on teabot {teabot.__version__}: the newest needs "
            f"teabot {plugin.newest.teabot}. Upgrade teabot first.",
            err=True,
        )
        raise typer.Exit(1)
    return chosen


def install_line(requirements: Sequence[str]) -> str:
    """The line that installs these through Compose, without uv on the machine."""
    return "docker compose run --rm uv add " + " ".join(f'"{r}"' for r in requirements)


def _uv_add(requirements: Sequence[str]) -> bool:
    """Add `requirements` with uv in the instance's folder. False, with the line to run instead, when uv is not
    here or this is not an instance's folder."""
    uv = shutil.which("uv")
    if uv is None or not PYPROJECT.exists():
        typer.echo("Run this in your instance's folder to install:")
        typer.echo(f"  {install_line(requirements)}")
        return False
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    done = subprocess.run([uv, "add", "--no-sync", *requirements], env=env, check=False)
    if done.returncode != 0:
        raise typer.Exit(done.returncode)
    return True


def _next_steps() -> None:
    typer.echo("Commit pyproject.toml and uv.lock, then rebuild: docker compose up -d --build")


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
        chosen = plugin.for_teabot()
        version = chosen.version if chosen is not None else f"needs teabot {plugin.newest.teabot}"
        typer.echo(f"{plugin.id:<20} {version:<10} {plugin.description}")
    if not shown:
        typer.echo("No plugins match.")


@app.command("show")
def show(plugin_id: Annotated[str, typer.Argument(help="The plugin's id.")], hub: Hub = DEFAULT_HUB) -> None:
    """Show one plugin: what it does, what it contacts, what it depends on, and how to install it."""
    plugin = _one(hub, plugin_id)
    chosen = _runnable(plugin)
    typer.echo(f"{plugin.id} {chosen.version}: {plugin.description}")
    typer.echo(f"  source        {plugin.repository} at {chosen.commit[:12]}")
    typer.echo(f"  contacts      {chosen.external_connections or 'none given'}")
    typer.echo(f"  depends on    teabot {chosen.teabot}; {', '.join(chosen.dependencies) or 'nothing else'}")
    typer.echo(f"  install       uv run teabot hub add {plugin.id}")
    typer.echo(f"  without uv    {install_line([chosen.requirement])}")


@app.command("add")
def add(plugin_id: Annotated[str, typer.Argument(help="The plugin's id.")], hub: Hub = DEFAULT_HUB) -> None:
    """Install a plugin at the newest reviewed version this teabot runs, or move an installed one to it."""
    plugin = _one(hub, plugin_id)
    chosen = _runnable(plugin)
    typer.echo(f"{plugin.id} contacts: {chosen.external_connections or 'none given'}")
    if _uv_add([chosen.requirement]):
        typer.echo(f"Added {plugin.package} {chosen.version} at {chosen.commit[:12]}.")
        _next_steps()
        typer.echo(f"Then, in each server that wants it, /plugins enable plugin:{plugin.id}")


@app.command("outdated")
def outdated(hub: Hub = DEFAULT_HUB) -> None:
    """List the installed hub plugins with a newer reviewed version this teabot runs, or that are delisted."""
    have = installed(PYPROJECT)
    if not have:
        typer.echo("No plugins from the hub are installed here.")
        return
    listed = {p.package: p for p in _load(hub).values()}
    for package, commit in sorted(have.items()):
        plugin = listed.get(package)
        chosen = plugin.for_teabot() if plugin is not None else None
        if plugin is None:
            typer.echo(f"{package:<26} no longer listed on the hub; read why at {HUB_PAGE}")
        elif chosen is None or chosen.commit == commit:
            typer.echo(f"{package:<26} up to date")
        else:
            typer.echo(
                f"{package:<26} {commit[:12]} -> {chosen.commit[:12]}: uv run teabot hub add {plugin.id}"
            )


@app.command("sync")
def sync(
    skip: Annotated[
        list[str] | None, typer.Option(help="A plugin's id to leave out. Repeat for more.")
    ] = None,
    check: Annotated[
        bool, typer.Option("--check", help="Say what would change, and change nothing.")
    ] = False,
    hub: Hub = DEFAULT_HUB,
) -> None:
    """Install every listed plugin at the newest reviewed version this teabot runs, as a service that offers the
    whole hub to its servers does. Each server still turns on only the plugins it wants. With --check, it exits
    1 when something would change, for a scheduled job to notice."""
    listed = _load(hub)
    found = plan_sync(listed, installed(PYPROJECT), skip=frozenset(skip or []))
    for change in found.changes:
        verb = "install" if change.was is None else f"move from {change.was[:12]} to"
        typer.echo(f"{change.plugin.id:<20} {verb} {change.to.version} at {change.to.commit[:12]}")
    for plugin in found.too_new:
        typer.echo(f"{plugin.id:<20} left out: every reviewed version needs teabot {plugin.newest.teabot}")
    for package in found.delisted:
        typer.echo(f"{package:<26} no longer listed on the hub: remove it with uv remove {package}")
    if not found.changes:
        typer.echo("Every listed plugin is installed at its newest reviewed version for this teabot.")
        return
    if check:
        raise typer.Exit(1)
    if _uv_add([c.to.requirement for c in found.changes]):
        _next_steps()
