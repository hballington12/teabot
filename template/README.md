# Instance template

- The starting point for a new teapot instance (D42, D43). It is filled in during WP5.1.
- `compose.yaml`: Postgres for now, used for development and tests. Start it with `docker compose -f template/compose.yaml up -d postgres`. The owner password defaults to `teapot` and the port to `55432`, which avoids a Postgres already on 5432, and `TEAPOT_DB_OWNER_PASSWORD` and `TEAPOT_DB_PORT` override them.
