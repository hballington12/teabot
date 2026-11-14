"""`teabot run`: start a bot process (D34). systemd or Compose calls this."""

from pathlib import Path
from typing import Annotated

import typer

from teabot import app as runner
from teabot.logs import setup_logging
from teabot.settings import DEFAULT_ENV_FILE, load_settings


def run(
    env_file: Annotated[Path, typer.Option(help="The instance's env file.")] = DEFAULT_ENV_FILE,
) -> None:
    """Migrate, connect to Discord and serve until stopped."""
    settings = load_settings(env_file)
    setup_logging(settings.log_level, settings.resolved_log_format)
    raise typer.Exit(runner.run(settings))
