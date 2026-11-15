# Core tests

- Run with `uv run pytest`. They need a Postgres 16 or later server.
- Locally, start it with `docker compose -f template/compose.yaml up -d postgres`.
- `conftest.py` loads `teabot.testing.fixtures`, the same fixtures plugin authors get. They read the server's address from `TEABOT_TEST_PG_HOST`, `TEABOT_TEST_PG_PORT`, `TEABOT_TEST_PG_USER` and `TEABOT_TEST_PG_PASSWORD`, defaulting to the Compose values.
- pytest-postgresql gives each test that asks for `postgresql` a fresh database.
- `db/`, `core/`, `adapters/`, `auth/`, `builtin/`, `cli/`, `sdk/` and `testing/` mirror the packages they test, and the files at the top test the modules at the top of `teabot`, such as `test_gateway_events.py` for the client in `app.py`.
- Plugin tests live in `plugins/<id>/tests/`, not here.
