"""Shared fixtures. Tests run against a real Postgres (D34).

The server comes from `template/compose.yaml` locally and from a service container in CI.
Its address is read from the TEAPOT_TEST_PG_* variables, with the Compose defaults.
pytest-postgresql creates a fresh database for each test that asks for one.
"""

import os

from pytest_postgresql import factories

postgresql_noproc = factories.postgresql_noproc(  # pyright: ignore[reportUnknownMemberType]
    host=os.environ.get("TEAPOT_TEST_PG_HOST", "127.0.0.1"),
    port=int(os.environ.get("TEAPOT_TEST_PG_PORT", "55432")),
    user=os.environ.get("TEAPOT_TEST_PG_USER", "teapot_owner"),
    password=os.environ.get("TEAPOT_TEST_PG_PASSWORD", "teapot"),
)
postgresql = factories.postgresql("postgresql_noproc")
