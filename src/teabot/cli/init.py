"""`teabot init`: set up a new instance (D43).

It generates the database passwords into the env file, creates the database roles, and prints the Discord
application settings to use, with the invite link for the application the token belongs to.
"""

import asyncio
import base64
import binascii
import secrets
from pathlib import Path
from typing import Annotated

import asyncpg
import typer

from teabot.db.bootstrap import BootstrapReport, bootstrap
from teabot.db.naming import Naming
from teabot.envfile import read_values, set_values
from teabot.settings import DEFAULT_ENV_FILE, Settings, load_settings

PASSWORD_SETTINGS = ("TEABOT_DB_APP_PASSWORD", "TEABOT_DB_PLUGINS_PASSWORD")
# Administrator: the bot holds near-Administrator power, and the role hierarchy keeps it below the senior
# roles (D26).
INVITE = "https://discord.com/oauth2/authorize?client_id={}&scope=bot+applications.commands&permissions=8"


def application_id(token: str) -> int | None:
    """The bot's ID, which a token's first part encodes in base64, or None when it is not a token."""
    first = token.split(".", maxsplit=1)[0]
    try:
        # Discord strips the padding. Decoding ignores any beyond what is needed, so two always suffice.
        decoded = base64.urlsafe_b64decode(first + "==").decode()
    except (binascii.Error, UnicodeDecodeError):
        return None
    return int(decoded) if decoded.isdigit() else None


def discord_settings(token: str) -> list[str]:
    """What to set on the Discord application, and how to invite it."""
    found = application_id(token)
    return [
        "Discord application settings:",
        "- Bot tab: turn on the Server Members Intent. Turn on Message Content only for TEABOT_MESSAGE_CONTENT=true.",
        f"- Invite: {INVITE.format('<application id>' if found is None else found)}",
        "- In each server, drag the bot's role below the owner's and senior staff roles (D26).",
        "- Invite one teabot instance to a server, never two: both would answer its commands.",
    ]


def _fill_missing_passwords(env_file: Path, *, rotate: bool = False) -> list[str]:
    """Generate the database passwords the env file lacks, or with `rotate` all of them."""
    present = read_values(env_file)
    missing = [name for name in PASSWORD_SETTINGS if rotate or not present.get(name)]
    if missing:
        set_values(env_file, {name: secrets.token_urlsafe(32) for name in missing})
    return missing


async def _bootstrap(
    settings: Settings, admin_user: str | None, admin_password: str | None
) -> BootstrapReport:
    conn = await asyncpg.connect(
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
        user=admin_user or settings.db_owner_user,
        password=admin_password if admin_user else settings.db_owner_password.get_secret_value(),
    )
    try:
        return await bootstrap(
            conn,
            Naming(settings.db_role_prefix),
            settings.db_app_password.get_secret_value(),
            settings.db_plugins_password.get_secret_value(),
        )
    finally:
        await conn.close()


def init(
    env_file: Annotated[Path, typer.Option(help="The instance's env file.")] = DEFAULT_ENV_FILE,
    admin_user: Annotated[
        str | None, typer.Option(help="A superuser for the set_config revoke. Defaults to the owner.")
    ] = None,
    admin_password: Annotated[str | None, typer.Option(help="The superuser's password.")] = None,
    rotate: Annotated[
        bool, typer.Option("--rotate", help="Replace the app and plugins passwords, such as after a leak.")
    ] = False,
) -> None:
    """Generate missing database passwords into the env file, then create the database roles, or give them the
    new passwords."""
    for name in _fill_missing_passwords(env_file, rotate=rotate):
        typer.echo(f"{'replaced' if rotate else 'generated'} {name} in {env_file}")
    settings = load_settings(env_file)
    report = asyncio.run(_bootstrap(settings, admin_user, admin_password))
    for role in report.created_roles:
        typer.echo(f"created role {role}")
    if not report.set_config_revoked:
        typer.echo(
            "warning: set_config is still executable by PUBLIC; rerun with --admin-user as a superuser"
        )
    typer.echo("database ready")
    if rotate:
        typer.echo("Restart teabot now: it still holds the old passwords, which no longer work.")
    for line in discord_settings(settings.discord_token.get_secret_value()):
        typer.echo(line)
