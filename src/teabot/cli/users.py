"""`teabot users`: deleting a member's data on their request (D11)."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer

from teabot.cli.plugins import _owner_login  # pyright: ignore[reportPrivateUsage]
from teabot.core.member_data import Deleted, delete_member_data
from teabot.db.naming import Naming
from teabot.db.pool import open_pool
from teabot.settings import DEFAULT_ENV_FILE, Settings, load_settings

app = typer.Typer(name="users", help="Act on one member's data.", no_args_is_help=True)


async def _delete_for(settings: Settings, user_id: int, guild_id: int | None) -> Deleted:
    pool = await open_pool(_owner_login(settings), 1)
    try:
        async with pool.acquire() as conn:
            return await delete_member_data(conn, Naming(settings.db_role_prefix), user_id, guild_id)
    finally:
        await pool.close()


def report(deleted: Deleted) -> list[str]:
    """What the command prints once it is done."""
    if not deleted.total:
        return ["Nothing held that member's ID."]
    lines = [f"  {table}: {rows} rows" for table, rows in deleted.plugins.items()]
    lines += [f"  {name}: {rows} rows" for name, rows in deleted.core.items()]
    return ["Deleted or anonymised:", *lines]


@app.command("delete")
def delete(
    user_id: Annotated[int, typer.Argument(help="The member's Discord ID.")],
    server: Annotated[int | None, typer.Option(help="Only this server's data, by its ID.")] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Do not ask first.")] = False,
    env_file: Annotated[Path, typer.Option(help="The instance's env file.")] = DEFAULT_ENV_FILE,
) -> None:
    """Delete a member's data in every plugin, and take their ID out of the core's records."""
    where = f"in server {server}" if server is not None else "in every server"
    if not yes and not typer.confirm(
        f"Delete the data of member {user_id} {where}? This cannot be undone.", default=False
    ):
        typer.echo("Nothing was changed.")
        raise typer.Exit(1)
    for line in report(asyncio.run(_delete_for(load_settings(env_file), user_id, server))):
        typer.echo(line)
