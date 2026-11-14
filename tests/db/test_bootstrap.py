"""The database bootstrap behind `teabot init`."""

from typing import Any

import pytest

from teabot.db.bootstrap import bootstrap
from teabot.db.naming import InvalidPluginId, Naming
from teabot.db.pool import ConnectionInfo, Login, connect
from teabot.db.types import Conn


async def test_creates_roles_then_is_idempotent(admin: Conn, naming: Naming) -> None:
    first = await bootstrap(admin, naming, "a", "p")
    assert set(first.created_roles) == {naming.app_role, naming.plugins_role}
    assert first.set_config_revoked
    second = await bootstrap(admin, naming, "a2", "p2")
    assert second.created_roles == ()


async def test_plugins_role_does_not_inherit(admin: Conn, naming: Naming) -> None:
    await bootstrap(admin, naming, "a", "p")
    inherit = await admin.fetchval("SELECT rolinherit FROM pg_roles WHERE rolname = $1", naming.plugins_role)
    assert inherit is False


async def test_set_config_is_revoked_from_public(admin: Conn, naming: Naming) -> None:
    await bootstrap(admin, naming, "a", "p")
    public_can = await admin.fetchval(
        "SELECT has_function_privilege('public', 'pg_catalog.set_config(text, text, boolean)', 'EXECUTE')"
    )
    app_can = await admin.fetchval(
        "SELECT has_function_privilege($1, 'pg_catalog.set_config(text, text, boolean)', 'EXECUTE')",
        naming.app_role,
    )
    assert public_can is False
    assert app_can is True


@pytest.mark.parametrize("bad", ["", "a", "Alpha", "1abc", "has-dash", "x" * 33, 'a"; drop'])
def test_plugin_ids_are_checked(bad: str) -> None:
    with pytest.raises(InvalidPluginId):
        Naming().plugin_role(bad)


async def test_without_a_superuser_set_config_is_reported_not_revoked(
    admin: Conn, naming: Naming, owner_kwargs: dict[str, Any], info: ConnectionInfo
) -> None:
    owner = f"{naming.prefix}_owner"
    database = owner_kwargs["database"]
    await admin.execute(f"CREATE ROLE \"{owner}\" LOGIN CREATEROLE PASSWORD 'o'")
    await admin.execute(f'ALTER DATABASE "{database}" OWNER TO "{owner}"')
    try:
        conn = await connect(Login(info, owner, "o"))
        try:
            report = await bootstrap(conn, naming, "a", "p")
        finally:
            await conn.close()
        assert report.set_config_revoked is False
        assert set(report.created_roles) == {naming.app_role, naming.plugins_role}
    finally:
        await admin.execute(f'ALTER DATABASE "{database}" OWNER TO "{owner_kwargs["user"]}"')


async def test_both_login_roles_are_noinherit(admin: Conn, naming: Naming) -> None:
    await bootstrap(admin, naming, "a", "p")
    rows = await admin.fetch(
        "SELECT rolname, rolinherit FROM pg_roles WHERE rolname = ANY($1::text[])",
        [naming.app_role, naming.plugins_role],
    )
    assert {r["rolname"]: r["rolinherit"] for r in rows} == {
        naming.app_role: False,
        naming.plugins_role: False,
    }
