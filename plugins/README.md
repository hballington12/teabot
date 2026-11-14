# Development plugins

- The first-party plugins ship inside teabot, in `src/teabot/plugins/`. This directory holds only plugins for teabot's own tests, each its own package and a member of the uv workspace.
- `devtools/`: development only, in the `dev` group. Exercises its own table, the core's refusal of plugin roles, a failing setup, and plan then apply (`clear_notes`, destructive, with progress). It imports only `teabot.sdk`; an import-linter contract checks that.
- `devtools_twin/`: declares the id `devtools` a second time, to check duplicates are refused (D46). Installed only with `uv sync --group duplicate-check`.
- Each keeps its tests in its own `tests/`, using `teabot.testing`. The root `pytest` run collects them.
