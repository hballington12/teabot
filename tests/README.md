# Core tests

- Run with `uv run pytest`. They need a Postgres 16 or later server.
- Locally, start it with `docker compose -f template/compose.yaml up -d postgres`.
- `conftest.py` reads the server's address from `TEAPOT_TEST_PG_HOST`, `TEAPOT_TEST_PG_PORT`, `TEAPOT_TEST_PG_USER` and `TEAPOT_TEST_PG_PASSWORD`, defaulting to the Compose values.
- pytest-postgresql gives each test that asks for `postgresql` a fresh database.
- `db/` and `core/` mirror the packages they test. Shared fixtures live in `conftest.py`.
- Plugin tests live in `plugins/<id>/tests/`, not here.
