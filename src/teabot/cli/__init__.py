"""The `teabot` command line (D34)."""

from typing import Annotated

import typer

import teabot
from teabot.cli import plugins
from teabot.cli.init import init
from teabot.cli.new_plugin import new_plugin
from teabot.cli.run import run

app = typer.Typer(name="teabot", help="Run and operate a teabot instance.", no_args_is_help=True)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"teabot {teabot.__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_print_version, help="Show the version.")
    ] = False,
) -> None:
    """Run and operate a teabot instance."""


app.command()(init)
app.command()(run)
app.command("new-plugin")(new_plugin)
app.add_typer(plugins.app)
