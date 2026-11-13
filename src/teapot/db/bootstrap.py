"""Database bootstrap for `teapot init` (D9, spike S1).

Creates the two login roles, or updates their passwords, and revokes `set_config` from `PUBLIC`.
The revoke needs a superuser. Without one, the bootstrap reports that the injection limit of D9 falls back
to review, and carries on.
"""

import contextlib
import logging
from dataclasses import dataclass

import asyncpg

from teapot.db.naming import Naming
from teapot.db.types import Conn

log = logging.getLogger(__name__)

SET_CONFIG = "pg_catalog.set_config(text, text, boolean)"


@dataclass(frozen=True)
class BootstrapReport:
    created_roles: tuple[str, ...]
    set_config_revoked: bool


async def _quote(conn: Conn, value: str) -> str:
    quoted: str = await conn.fetchval("SELECT quote_literal($1)", value)
    return quoted


async def _ensure_login_role(conn: Conn, role: str, password: str) -> bool:
    """Both login roles are NOINHERIT: the plugins role must never use a plugin role's rights without
    `SET ROLE` (S1), and the app role is granted no roles at all."""
    exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
    verb = "ALTER" if exists else "CREATE"
    await conn.execute(f'{verb} ROLE "{role}" LOGIN NOINHERIT PASSWORD {await _quote(conn, password)}')
    return not exists


async def _revoke_set_config(conn: Conn, naming: Naming) -> bool:
    """Try the revoke, then report what the privileges actually are.

    A role that may not revoke gets a warning from Postgres, not an error, so success cannot be inferred
    from the absence of an exception.
    """
    owner = await conn.fetchval("SELECT current_user")
    with contextlib.suppress(asyncpg.InsufficientPrivilegeError):
        async with conn.transaction():
            await conn.execute(f"REVOKE EXECUTE ON FUNCTION {SET_CONFIG} FROM PUBLIC")
            await conn.execute(f'GRANT EXECUTE ON FUNCTION {SET_CONFIG} TO "{naming.app_role}", "{owner}"')
    public_can = await conn.fetchval("SELECT has_function_privilege('public', $1, 'EXECUTE')", SET_CONFIG)
    if public_can:
        log.warning(
            "cannot revoke set_config without a superuser; "
            "a plugin's SQL injection bug could then change its role, so review is the only limit (D9)"
        )
    return not public_can


async def bootstrap(conn: Conn, naming: Naming, app_password: str, plugins_password: str) -> BootstrapReport:
    """Run on the instance's database as its owner, or as a superuser for the `set_config` revoke."""
    created: list[str] = []
    if await _ensure_login_role(conn, naming.app_role, app_password):
        created.append(naming.app_role)
    if await _ensure_login_role(conn, naming.plugins_role, plugins_password):
        created.append(naming.plugins_role)
    database = await conn.fetchval("SELECT current_database()")
    roles = f'"{naming.app_role}", "{naming.plugins_role}"'
    await conn.execute(f'GRANT CONNECT ON DATABASE "{database}" TO {roles}')
    await conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    revoked = await _revoke_set_config(conn, naming)
    return BootstrapReport(tuple(created), revoked)
