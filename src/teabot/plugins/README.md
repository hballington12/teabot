# teabot.plugins

- teabot's first-party plugins. They ship inside the `teabot` package, the way RuneLite ships its core plugins in the client.
- Each is registered in `pyproject.toml` under `[project.entry-points."teabot.plugins"]`, and loads exactly as a third-party plugin does.
- Each is off in a server until `/plugins enable plugin:<id>`. `TEABOT_DISABLED_PLUGINS` turns one off for a whole instance.
- Each imports only `teabot.sdk`, which an import-linter contract checks, so they stay honest examples for plugin authors.
- `announcements/`: post an announcement to a channel, now or later.
- `giveaways/`: members enter, and winners are drawn when time is up. The tutorial's worked example.
- Their tests are in `tests/plugins/<id>/`, each with its `snapshot.json`.
