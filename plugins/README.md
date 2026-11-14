# First-party plugins

- Each plugin is its own package in a subdirectory and a member of the uv workspace (D42). It imports only `teabot.sdk`; an import-linter contract checks that.
- `announcements/`: post announcements to a channel, now (`post`) or later (`schedule`, a job on the queue). The first real plugin (D41).
- `devtools/`: development only, in the `dev` group. Exercises its own table, the core's refusal of plugin roles, a failing setup, and plan then apply (`clear_notes`, destructive, with progress).
- `devtools_twin/`: declares the id `devtools` a second time, to check duplicates are refused (D46). Installed only with `uv sync --group duplicate-check`.
- Each plugin keeps its tests in its own `tests/`, using `teabot.testing`. The root `pytest` run collects them.
