# teapot package

- `__init__.py`: the package version.
- `__main__.py`: `python -m teapot`, the same CLI as the `teapot` script.
- `cli/`: the `teapot` command line (D34): `init`, `run` and `plugins list`.
- `settings.py`: instance settings from `TEAPOT_*` variables and `teapot.env`. `template/teapot.env.example` lists them all.
- `logs.py`: logging setup, text in dev mode and JSON lines in production, both carrying `extra=` fields.
- `app.py`: `teapot run`'s real parts: the Discord client that locks its shards in `setup_hook`, embedded uvicorn, and `main`.
- `runtime.py`: the runner's orchestration over protocols for the client and server, tested with real database parts.
- `health.py`: the report behind `/healthz`.
- `web.py`: the HTTP app, `/healthz` for now.
- `envfile.py`: edits to an env file that keep every other line, used by `teapot init`.
- `db/`: database access, see its README.
- `core/`: actions, plugins, the queue and process ownership, see its README.
- `sdk/`: the public plugin API (D45). Plugins import only from here.
- `py.typed`: marks the package as typed for plugin authors.

The rest of the layout in `docs/plan.md` arrives work package by work package.
