"""`teabot check [path]`: run the plugin review checklist against a plugin project (D45)."""

from pathlib import Path
from typing import Annotated

import typer

from teabot.lint import check_project


def check(
    path: Annotated[Path, typer.Argument(help="The plugin's directory, such as plugins/raffles.")] = Path(
        "."
    ),
) -> None:
    """Check a plugin against the review checklist: its imports, its SQL, its clock and its README."""
    problems = check_project(path)
    for problem in problems:
        typer.echo(str(problem))
    if problems:
        raise typer.Exit(1)
    typer.echo("no problems found")
