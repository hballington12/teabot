"""The database bootstrap behind `teapot init` (WP1.3)."""

import pytest

from teapot.db.bootstrap import bootstrap
from teapot.db.naming import InvalidPluginId, Naming
from teapot.db.types import Conn


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
