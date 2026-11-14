# Your plugins

- Each plugin you write for this instance lives here as `plugins/<id>/`, a uv workspace member (D44).
- `uv run teabot new-plugin <id>` scaffolds one: entry point, manifest, first migration, README and tests.
- A plugin imports only `teabot.sdk`. `docs/plugin-authoring.md` in the teabot repository covers the rest.
