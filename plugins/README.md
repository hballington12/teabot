# First-party plugins

- Each plugin is its own package in a subdirectory and a member of the uv workspace (D42). It imports only `teapot.sdk`; an import-linter contract checks that.
- `announcements/`: post announcements to a channel. The first real plugin (D41).
- `devtools/`: development only, in the `dev` group. Exercises its own table, the core's refusal of plugin roles, and a failing setup.
- `devtools_twin/`: declares the id `devtools` a second time, to check duplicates are refused (D46). Installed only with `uv sync --group duplicate-check`.
- Each plugin keeps its tests in its own `tests/`, using `teapot.testing`. The root `pytest` run collects them.
