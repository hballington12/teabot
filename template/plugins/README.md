# Your plugins

- Each plugin you write for this instance lives here as `plugins/<id>/`, a uv workspace member.
- `uv run teabot new-plugin <id>` scaffolds one: a one-file plugin, its first migration, a README, tests and a snapshot test.
- A plugin imports only `teabot.sdk`. Writing one is covered at https://teabot-dev.github.io/teabot/plugins/
