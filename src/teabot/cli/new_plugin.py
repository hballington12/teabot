"""`teabot new-plugin <id>`: scaffold a plugin package in the instance (D44, D45).

It writes `plugins/<id>/` as a uv workspace member: the entry point, a one-file plugin with one example action,
a first migration, a README with its "External connections" section, tests through `teabot.testing` and a
snapshot test. An id an installed plugin already has is refused, since two would both fail to load (D46). The
templates are in `scaffold/`.
"""

from importlib.metadata import entry_points
from pathlib import Path
from string import Template
from typing import Annotated

import typer

import teabot
from teabot.sdk.ids import InvalidPluginId, check_plugin_id_free

SCAFFOLD = Path(__file__).parent / "scaffold"


def files_for(plugin_id: str) -> dict[str, str]:
    """Each file of the package, by its path inside `plugins/<id>/`, to the template it is made from."""
    package = f"src/teabot_{plugin_id}"
    return {
        "pyproject.toml": "pyproject.toml.tmpl",
        "README.md": "README.md.tmpl",
        f"{package}/__init__.py": "plugin.py.tmpl",
        f"{package}/migrations/0001_greetings.sql": "migration.sql.tmpl",
        f"{package}/py.typed": "",
        f"tests/test_{plugin_id}.py": "test_plugin.py.tmpl",
        f"tests/test_{plugin_id}_snapshot.py": "test_snapshot.py.tmpl",
    }


def class_name(plugin_id: str) -> str:
    return "".join(part.capitalize() for part in plugin_id.split("_"))


def teabot_range(version: str) -> str:
    """The teabot releases a new plugin works with: this major version, from its first release (D45)."""
    major = int(version.split(".", maxsplit=1)[0])
    return f"teabot>={major}.0,<{major + 1}"


def write_package(root: Path, plugin_id: str) -> None:
    values = {
        "id": plugin_id,
        "class_name": class_name(plugin_id),
        "teabot": teabot_range(teabot.__version__),
    }
    for path, template in files_for(plugin_id).items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        text = Template((SCAFFOLD / template).read_text()).substitute(values) if template else ""
        target.write_text(text)


def new_plugin(
    plugin_id: Annotated[str, typer.Argument(help="The plugin's id, such as raffles.", metavar="ID")],
    into: Annotated[Path, typer.Option(help="The instance's plugins directory.")] = Path("plugins"),
) -> None:
    """Scaffold a plugin package in the instance's plugins directory."""
    try:
        check_plugin_id_free(plugin_id)
    except InvalidPluginId as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    taken = {ep.name: ep.dist.name if ep.dist else ep.value for ep in entry_points(group="teabot.plugins")}
    if plugin_id in taken:
        typer.echo(
            f"error: the installed package {taken[plugin_id]} already has a plugin with the id {plugin_id}; "
            "choose another, since two plugins with one id both fail to load",
            err=True,
        )
        raise typer.Exit(1)
    root = into / plugin_id
    if root.exists():
        typer.echo(f"error: {root} already exists", err=True)
        raise typer.Exit(1)
    write_package(root, plugin_id)
    typer.echo(f"created {root}")
    typer.echo(
        f"next: uv lock, then uv run --env-file .env --package teabot-{plugin_id} pytest {into / plugin_id}"
    )
    typer.echo(f"then restart teabot, and enable it in a server with /plugins enable plugin:{plugin_id}")
