"""`teapot init`: generate the database passwords and bootstrap the roles (D43, WP1.3).

The rest of instance setup (printing the Discord application settings) arrives in WP7.2.
"""

import asyncio
import secrets
from pathlib import Path
from typing import Annotated

import asyncpg
import typer

from teapot.db.bootstrap import BootstrapReport, bootstrap
from teapot.db.naming import Naming
from teapot.envfile import read_values, set_values
from teapot.settings import DEFAULT_ENV_FILE, Settings, load_settings

PASSWORD_SETTINGS = ("TEAPOT_DB_APP_PASSWORD", "TEAPOT_DB_PLUGINS_PASSWORD")


def _fill_missing_passwords(env_file: Path) -> list[str]:
    present = read_values(env_file)
    missing = [name for name in PASSWORD_SETTINGS if not present.get(name)]
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
) -> None:
    """Generate missing database passwords into the env file, then create the database roles."""
    for name in _fill_missing_passwords(env_file):
        typer.echo(f"generated {name} in {env_file}")
    settings = load_settings(env_file)
    report = asyncio.run(_bootstrap(settings, admin_user, admin_password))
    for role in report.created_roles:
        typer.echo(f"created role {role}")
    if not report.set_config_revoked:
        typer.echo(
            "warning: set_config is still executable by PUBLIC; rerun with --admin-user as a superuser"
        )
    typer.echo("database ready")
