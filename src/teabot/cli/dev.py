"""`teabot dev`: run the bot, and restart it whenever a plugin's code changes.

Restarting the whole process, instead of reloading modules in a live one, means each run is a clean start: the
plugins load, migrate, and sync their commands to the servers where they are enabled, as `teabot run` does.
In an instance folder, it reaches the Compose Postgres on this machine, through the port and owner password
in `.env`.
"""

import os
import shlex
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Annotated

import typer
from watchfiles import DefaultFilter, run_process

from teabot.envfile import read_values
from teabot.settings import DEFAULT_ENV_FILE

COMPOSE_FILE = Path("compose.yaml")
COMPOSE_ENV = Path(".env")
WATCHED = (".py", ".sql", ".toml", ".env", ".md")


class CodeFilter(DefaultFilter):
    """Changes that matter to the bot: code, migrations, project files and the env file."""

    def __call__(self, change: object, path: str) -> bool:
        return super().__call__(change, path) and path.endswith(WATCHED)  # pyright: ignore[reportArgumentType]


def compose_env(environ: Mapping[str, str], folder: Path = Path()) -> dict[str, str]:
    """What the bot needs to reach an instance's Compose Postgres from this machine, for each variable the
    environment does not already set. Nothing outside an instance folder."""
    if not (folder / COMPOSE_FILE).exists():
        return {}
    compose = read_values(folder / COMPOSE_ENV)
    wanted = {
        "TEABOT_DB_HOST": "127.0.0.1",
        "TEABOT_DB_PORT": compose.get("TEABOT_DB_PORT", "55432"),
        "TEABOT_DB_OWNER_PASSWORD": compose.get("TEABOT_DB_OWNER_PASSWORD", ""),
    }
    return {name: value for name, value in wanted.items() if value and name not in environ}


def watched(paths: Sequence[Path], env_file: Path) -> list[Path]:
    """The paths to watch: those given, or the instance's `plugins` folder, and the env file."""
    chosen = list(paths) or ([Path("plugins")] if Path("plugins").is_dir() else [Path()])
    return [p for p in [*chosen, env_file] if p.exists()]


def command(env_file: Path) -> str:
    return shlex.join([sys.executable, "-m", "teabot", "run", "--env-file", str(env_file)])


def dev(
    env_file: Annotated[Path, typer.Option(help="The instance's env file.")] = DEFAULT_ENV_FILE,
    watch: Annotated[
        list[Path] | None, typer.Option(help="A folder or file to watch; the plugins folder by default.")
    ] = None,
) -> None:
    """Run the bot, and restart it when a plugin's code, migrations or the env file change."""
    os.environ.update(compose_env(os.environ))
    paths = watched(watch or [], env_file)
    typer.echo(f"Watching {', '.join(str(p) for p in paths)}. Stop with Ctrl+C.")
    if COMPOSE_FILE.exists():
        typer.echo("Stop the Compose bot first, so the two do not share the bot: docker compose stop bot")
    run_process(
        *paths,
        target=command(env_file),
        target_type="command",
        watch_filter=CodeFilter(),
        callback=lambda changes: typer.echo(
            f"Changed: {', '.join(sorted({c[1] for c in changes}))}. Restarting."
        ),
        grace_period=1,
    )
