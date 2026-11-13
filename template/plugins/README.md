# Your plugins

- Each plugin you write for this instance lives here as `plugins/<id>/`, a uv workspace member (D44).
- `uv run teapot new-plugin <id>` scaffolds one: entry point, manifest, first migration, README and tests.
- A plugin imports only `teapot.sdk`. `docs/plugin-authoring.md` in the teapot repository covers the rest.
