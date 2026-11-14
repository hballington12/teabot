"""Per-run test database and role names, and cleanup of what killed runs left behind.

Every name carries the test process's pid. A run that is killed (for example a mutant that hangs under
mutator) leaves its databases and roles behind; the next session drops those whose pid is no longer alive.
Concurrent runs never share a name, so they never collide.
"""

import os
import re
import sys
from collections.abc import Callable
from typing import Any

import psycopg

DB_RE = re.compile(r"teabot_test_(\d+)(_\w+)?")
ROLE_RE = re.compile(r"t(\d+)r[0-9a-f]+_\w+")
LEGACY_ROLE_RE = re.compile(r"t[0-9a-f]{8}_\w+")
# Fixed names that earlier versions of this suite used before names carried the pid.
LEGACY_DATABASES = frozenset({"tests", "tests_tmpl"})
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ERROR_ACCESS_DENIED = 5
STILL_ACTIVE = 259


def run_db_name(pid: int) -> str:
    return f"teabot_test_{pid}"


def role_prefix(pid: int, token: str) -> str:
    return f"t{pid}r{token}"


def _alive_on_windows(pid: int) -> bool:
    """`os.kill(pid, 0)` sends CTRL_C_EVENT on Windows rather than probing, so ask the kernel instead."""
    import ctypes  # noqa: PLC0415

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED  # it exists but belongs to someone else
    try:
        return _still_active(kernel32, handle)
    finally:
        kernel32.CloseHandle(handle)


def _still_active(kernel32: Any, handle: int) -> bool:
    """An open process handle can belong to a process that has already exited, so read its exit code.
    Split from `_alive_on_windows` so each stays simple enough to pass CRAP where it never runs."""
    import ctypes  # noqa: PLC0415

    code = ctypes.c_ulong()
    return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == STILL_ACTIVE


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        return _alive_on_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _dead_runs(names: list[str], pattern: re.Pattern[str], legacy: Callable[[str], bool]) -> list[str]:
    """Names from runs whose pid is gone, plus the legacy names of earlier versions."""
    stale = [n for n in names if (m := pattern.fullmatch(n)) and not _alive(int(m.group(1)))]
    return stale + [n for n in names if legacy(n)]


def _stale_databases(conn: Any) -> list[str]:
    names = [r[0] for r in conn.execute("SELECT datname FROM pg_database").fetchall()]
    return _dead_runs(names, DB_RE, LEGACY_DATABASES.__contains__)


def _stale_roles(conn: Any) -> list[str]:
    names = [r[0] for r in conn.execute("SELECT rolname FROM pg_roles").fetchall()]
    return _dead_runs(names, ROLE_RE, lambda n: LEGACY_ROLE_RE.fullmatch(n) is not None)


def cleanup(conn: Any) -> None:
    """Drop dead runs' databases, then their roles. `DROP DATABASE` cannot run in a transaction, so this
    switches the psycopg connection to autocommit itself."""
    conn.autocommit = True
    for name in _stale_databases(conn):
        conn.execute(f'ALTER DATABASE "{name}" IS_TEMPLATE false')
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    for name in _stale_roles(conn):
        try:
            conn.execute(f'DROP OWNED BY "{name}"')
            conn.execute(f'DROP ROLE IF EXISTS "{name}"')
        except psycopg.errors.DependentObjectsStillExist:
            continue  # still owns objects in another database; a later session retries
