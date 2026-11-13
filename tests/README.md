# Core tests

- Run with `uv run pytest`. They need a Postgres 16 or later server.
- Locally, start it with `docker compose -f template/compose.yaml up -d postgres`.
- `conftest.py` loads `teapot.testing.fixtures`, the same fixtures plugin authors get. They read the server's address from `TEAPOT_TEST_PG_HOST`, `TEAPOT_TEST_PG_PORT`, `TEAPOT_TEST_PG_USER` and `TEAPOT_TEST_PG_PASSWORD`, defaulting to the Compose values.
- pytest-postgresql gives each test that asks for `postgresql` a fresh database.
- `db/`, `core/`, `adapters/`, `sdk/` and `testing/` mirror the packages they test.
- Plugin tests live in `plugins/<id>/tests/`, not here.
