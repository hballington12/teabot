# Changelog

Every release of `teabot`, `teabot-announcements` and the instance template, newest first. The versions follow semantic versioning, which `teabot.sdk` keeps from 1.0 (D45). A **For operators** section lists any manual step an upgrade needs (D48).

## Unreleased

## 1.0.2 - 2026-11-14

Fixes from the first plugin authoring trial.

- Plugins can use array columns and array parameters. They failed with "permission denied for function set_config", because asyncpg calls it before looking up an array type.
- A failed job names its error and traceback in the log, and `harness.run_jobs()` raises the new `teabot.testing.JobFailed`, with the job's own exception as its cause.
- An integer field's `ge`, `le`, `gt` and `lt` become the slash option's minimum and maximum, so Discord checks them before sending.
- Without Postgres, the test fixtures stop at once and say how to start it, instead of retrying for a minute.
- `teabot new-plugin` declares a compatible teabot range, such as `teabot>=1.0,<2`.
- The `ctx.db` docstrings no longer claim that rows are filtered by server: every query must filter by `guild_id`.
- The plugin guide answers what the trial had to read teabot's code for: posting, config, confirming plans and making jobs due in tests, the retry schedule, and the refusal codes.
- asyncpg is pinned below 0.33.

## 1.0.1 - 2026-11-14

- A new README with the teabot icon and badges. The design decisions and the architecture moved to `docs/design.md` and `docs/architecture.md`.
- PyPI shows the project's links, keywords and classifiers.

## 1.0.0 - 2026-11-14

The first release.

- A plugin framework for Discord bots. Each action a plugin offers is a slash command, an MCP tool and a service API route at once, behind one call path that checks the member's Discord permissions on every call and records an audit trail.
- `teabot.sdk` 1.0: actions, jobs, per-server config, each plugin's own tables in its own schema and role, and plan then apply for destructive actions.
- Tokens for LLM clients and event backends, tied to a member and narrowed by risk and by action.
- Servers that add and remove the bot, with their data kept for a grace period and then purged.
- `teabot-announcements`: post an announcement now, or schedule it.
- `teabot init`, `teabot run`, `teabot plugins list | purge` and `teabot new-plugin`.
- The instance template, with a quick setup on Docker Compose and a careful one on a bare-metal host with continuous backups.
