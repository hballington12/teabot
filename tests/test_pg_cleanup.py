"""Leftovers from killed test runs are cleaned up, and never break the next run."""

import os
from typing import Any

import psycopg
import pytest

from teabot.testing.cleanup import cleanup, role_prefix, run_db_name

DEAD_PID = 2**22 + 12345  # above Linux's largest pid, so never alive


@pytest.fixture
def maintenance(teabot_pg_server: Any) -> Any:
    conn = psycopg.connect(
        host=teabot_pg_server.host,
        port=teabot_pg_server.port,
        user=teabot_pg_server.user,
        password=teabot_pg_server.password,
        dbname="postgres",
        autocommit=True,
    )
    yield conn
    conn.close()


def databases(conn: Any) -> set[str]:
    return {r[0] for r in conn.execute("SELECT datname FROM pg_database").fetchall()}


def roles(conn: Any) -> set[str]:
    return {r[0] for r in conn.execute("SELECT rolname FROM pg_roles").fetchall()}


def test_a_dead_runs_databases_and_roles_are_dropped(maintenance: Any) -> None:
    dead_db, dead_role = run_db_name(DEAD_PID), f"{role_prefix(DEAD_PID, 'ab12')}_app"
    maintenance.execute(f'CREATE DATABASE "{dead_db}"')
    maintenance.execute(f'CREATE DATABASE "{dead_db}_tmpl"')
    maintenance.execute(f'CREATE ROLE "{dead_role}"')
    maintenance.execute('CREATE ROLE "t0badcafe_app"')
    maintenance.execute('CREATE DATABASE "tests_tmpl"')
    cleanup(maintenance)
    assert {dead_db, f"{dead_db}_tmpl", "tests_tmpl"}.isdisjoint(databases(maintenance))
    assert {dead_role, "t0badcafe_app"}.isdisjoint(roles(maintenance))


def test_the_live_runs_database_is_kept(maintenance: Any) -> None:
    live_db = f"{run_db_name(os.getpid())}_keep"
    maintenance.execute(f'CREATE DATABASE "{live_db}"')
    try:
        cleanup(maintenance)
        assert live_db in databases(maintenance)
    finally:
        maintenance.execute(f'DROP DATABASE "{live_db}"')
