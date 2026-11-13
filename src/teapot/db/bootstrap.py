"""Database bootstrap for `teapot init` (D9, spike S1).

Creates the two login roles, or updates their passwords, and revokes `set_config` from `PUBLIC`.
The revoke needs a superuser. Without one, the bootstrap reports that the injection limit of D9 falls back
to review, and carries on.
"""

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


async def _ensure_login_role(conn: Conn, role: str, password: str, inherit: bool) -> bool:
    exists = await conn.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", role)
    inherit_sql = "INHERIT" if inherit else "NOINHERIT"
    verb = "ALTER" if exists else "CREATE"
    await conn.execute(f'{verb} ROLE "{role}" LOGIN {inherit_sql} PASSWORD {await _quote(conn, password)}')
    return not exists


async def _revoke_set_config(conn: Conn, naming: Naming) -> bool:
    owner = await conn.fetchval("SELECT current_user")
    try:
        async with conn.transaction():
            await conn.execute(f"REVOKE EXECUTE ON FUNCTION {SET_CONFIG} FROM PUBLIC")
            await conn.execute(f'GRANT EXECUTE ON FUNCTION {SET_CONFIG} TO "{naming.app_role}", "{owner}"')
    except asyncpg.InsufficientPrivilegeError:
        log.warning(
            "cannot revoke set_config without a superuser; "
            "a plugin's SQL injection bug could then change its role, so review is the only limit (D9)"
        )
        return False
    return True


async def bootstrap(conn: Conn, naming: Naming, app_password: str, plugins_password: str) -> BootstrapReport:
    """Run on the instance's database as its owner, or as a superuser for the `set_config` revoke."""
    created: list[str] = []
    if await _ensure_login_role(conn, naming.app_role, app_password, inherit=True):
        created.append(naming.app_role)
    if await _ensure_login_role(conn, naming.plugins_role, plugins_password, inherit=False):
        created.append(naming.plugins_role)
    database = await conn.fetchval("SELECT current_database()")
    roles = f'"{naming.app_role}", "{naming.plugins_role}"'
    await conn.execute(f'GRANT CONNECT ON DATABASE "{database}" TO {roles}')
    await conn.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    revoked = await _revoke_set_config(conn, naming)
    return BootstrapReport(tuple(created), revoked)
