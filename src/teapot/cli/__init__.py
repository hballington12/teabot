"""The `teapot` command line (D34). Subcommands arrive with their work packages."""

from typing import Annotated

import typer

import teapot

app = typer.Typer(name="teapot", help="Run and operate a teapot instance.", no_args_is_help=True)


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"teapot {teapot.__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_print_version, is_eager=True, help="Show the version.")
    ] = False,
) -> None:
    """Run and operate a teapot instance."""
