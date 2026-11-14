# Changelog

Every release of `teabot` and the instance template, newest first. Up to 1.0.2, the announcements plugin was released beside them as `teabot-announcements`. The versions follow semantic versioning, which `teabot.sdk` keeps from 1.0. A **For operators** section lists any manual step an upgrade needs.

<!-- --8<-- [start:releases] -->

## Unreleased

## 1.2.0 - 2026-11-14

### Documentation

- The documentation is a site, at https://hballington12.github.io/teabot/, in three parts: using teabot in a server, self-hosting, and writing plugins. Its tutorial builds a polls plugin, whose code is tested with teabot's own.

### Using teabot

- A plugin's command is shown only to members who hold the permissions all of its actions share, so most members no longer see commands they cannot use. teabot still checks each action's permissions on every call.
- `/tokens create` replies with the commands to paste into Claude Code, which read the token at a hidden prompt, and with the address and header any other MCP client needs.

### Self-hosting

- `./setup.sh` in the template sets up and starts an instance in one command: it asks for the bot token, writes `.env` and `teabot.env`, builds and starts the bot and Postgres, creates the database roles, and prints the invite link. It can be run again after a failure.
- The template's Compose file has a `uv` service, so changing an instance's plugins needs only Docker: `docker compose run --rm uv add teabot-foo`.
- The template's `.dockerignore` keeps `.env`, which holds the database owner's password, out of the image's build context.
- `teabot plugins purge` works in the bot's container, whose user has no name; the audit log records its id.
- `setup.sh` checks that it can reach Docker, and a failed health check says how to fix a wrong token.
- The template's `.gitignore` keeps database backups out of git, and the bare-metal setup installs Caddy and stops when `teabot init` fails.

### For operators

- To use `./setup.sh` and the `uv` service, copy `setup.sh`, `compose.yaml`, `.dockerignore` and `.gitignore` from the new template into your instance. Your `.env`, `teabot.env` and database are unchanged, and `setup.sh` keeps them.
- A bare-metal host gets Caddy from Ubuntu's packages when `setup-host.sh` runs again. A host that has Caddy already is unaffected.

### Writing plugins

- Plugin tests read the database password from the instance's `.env` themselves, so test commands need no `--env-file .env`.
- `teabot new-plugin` runs `uv lock` after writing the package; `--no-lock` skips it.

## 1.1.0 - 2026-11-14

### Writing plugins

- `Plugin(id, config=)` with `@plugin.action` and `@plugin.job` decorators. An action's inputs are its function's parameters, described by its docstring's `Args:` section, and its reply is its return value: a model, a list of models or a string. The tutorial builds a plugin with them step by step.
- `Context[Config]` gives actions and jobs `guild`, `actor`, `config` as the plugin's own model, `db`, `now`, `diff` and `report`.
- `TextChannel`, `Role` and `Member` parameters arrive as the Discord objects, checked to exist. The SDK's own `Guild`, `TextChannel`, `Member`, `Role` and `Message` protocols are implemented by discord.py's objects and by the test fakes alike.
- `needs=` takes Discord permission names, which pyright checks. `reply="public"` shows a reply to the channel.
- Typed queries: `fetch(Model, sql, ...)`, `fetchrow(Model, ...)` and `fetchval(int, ...)` validate each row.
- Typed, keyed jobs: `tx.schedule(job.bind(...), at=...)` checks the arguments against the job's function, scheduling the same bound job again moves it, and `tx.unschedule` removes it. Jobs carry the member who started them, and get the server's config.
- A destructive action's apply reads the confirmed plan as `ctx.diff`, whose entries carry a `key`.
- Messages mention nobody unless `ping=` names members.
- When a plugin loads, teabot imports every module of its package, and checks its schema: foreign keys and unique indexes include `guild_id`, and there are no views or `SECURITY DEFINER` functions.
- `teabot check` runs the review checklist's mechanical items: imports only from `teabot.sdk`, the clock read only through `ctx.now` and `now()`, no `SET` in SQL, and a README with "External connections".
- `teabot new-plugin` writes a one-file plugin on the decorators, with typed tests and a snapshot test.
- The `Plugin` protocol for objects with a `manifest` and `setup` is now `LoadablePlugin`. Such plugins load as before.

### Testing plugins

- `harness.call(action, ...)`, typed by the action, with `as_member(member)`, `plan`, `confirm`, `configure`, `run_job` to run a job again, and `advance`, which moves `ctx.now`, `now()` in the plugin's SQL, and when jobs fall due.
- The harness lints the plugin's package when it loads it.
- `teabot_snapshot` keeps a plugin's commands, MCP tools and job payloads in a committed file, and `pytest --teabot-accept` accepts a change.
- `HarnessFactory` types the `teabot_harness` fixture. Fake roles, and members with roles.

### Plugins

- The first-party plugins ship inside teabot, as RuneLite ships its core plugins in the client. Each is still off in a server until `/plugins enable`, and loads through the same entry points as any other plugin.
- giveaways: start a giveaway in a channel, let members enter, and draw the winners when time is up.
- announcements is written on the decorators. Announcements mention nobody, so an `@everyone` in the text stays plain text.
- `teabot new-plugin` refuses an id an installed plugin already has.

### For operators

- Remove `teabot-announcements` from your instance's dependencies, since teabot now carries it: `uv remove teabot-announcements`, then `uv lock --upgrade-package teabot`. With both installed, two plugins share the id `announcements`, and neither loads. Its config, tables and queued jobs carry over, since the id is unchanged.

### Operations

- `/admin job_status` shows a job's label and who started it.
- The release workflow publishes the GitHub release as a draft until its template is attached, and waits up to an hour for PyPI's index.

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

- A new README with the teabot icon and badges. The design decisions and the architecture moved into documents of their own.
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

<!-- --8<-- [end:releases] -->
