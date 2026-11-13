"""Per-run test database and role names, and cleanup of what killed runs left behind.

Every name carries the test process's pid. A run that is killed (for example a mutant that hangs under
mutator) leaves its databases and roles behind; the next session drops those whose pid is no longer alive.
Concurrent runs never share a name, so they never collide.
"""

import os
import re
from typing import Any

import psycopg

DB_RE = re.compile(r"teapot_test_(\d+)(_\w+)?")
ROLE_RE = re.compile(r"t(\d+)r[0-9a-f]+_\w+")
LEGACY_ROLE_RE = re.compile(r"t[0-9a-f]{8}_\w+")
# Fixed names that earlier versions of this suite used before names carried the pid.
LEGACY_DATABASES = frozenset({"tests", "tests_tmpl"})


def run_db_name(pid: int) -> str:
    return f"teapot_test_{pid}"


def role_prefix(pid: int, token: str) -> str:
    return f"t{pid}r{token}"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stale_databases(conn: Any) -> list[str]:
    names = [r[0] for r in conn.execute("SELECT datname FROM pg_database").fetchall()]
    stale = [n for n in names if (m := DB_RE.fullmatch(n)) and not _alive(int(m.group(1)))]
    return stale + [n for n in names if n in LEGACY_DATABASES]


def _stale_roles(conn: Any) -> list[str]:
    names = [r[0] for r in conn.execute("SELECT rolname FROM pg_roles").fetchall()]
    stale = [n for n in names if (m := ROLE_RE.fullmatch(n)) and not _alive(int(m.group(1)))]
    return stale + [n for n in names if LEGACY_ROLE_RE.fullmatch(n)]


def cleanup(conn: Any) -> None:
    """Drop dead runs' databases, then their roles. `conn` is an autocommit psycopg connection."""
    for name in _stale_databases(conn):
        conn.execute(f'ALTER DATABASE "{name}" IS_TEMPLATE false')
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    for name in _stale_roles(conn):
        try:
            conn.execute(f'DROP OWNED BY "{name}"')
            conn.execute(f'DROP ROLE IF EXISTS "{name}"')
        except psycopg.errors.DependentObjectsStillExist:
            continue  # still owns objects in another database; a later session retries
