# Implementation plan

How teapot gets built. The [README](../README.md) records the decisions (D1 to D50) and [`plan.md`](plan.md) describes what the finished milestones contain. This document turns those milestones into ordered work packages, each small enough to finish in a few focused commits.

## Ground rules

### Toolchain

- Python 3.12 or later, because the SDK uses PEP 695 generics (`class ActionSpec[I: BaseModel, O: BaseModel]`). Development and CI run 3.13, and CI also runs the test suite on 3.12.
- Postgres 16 or later. Ubuntu 24.04 ships 16, which covers the droplet and most self-hosters.
- uv for everything. `uv sync` sets up the workspace, and every command runs as `uv run ...`, with no `--with` flags.
- Typer for the `teapot` CLI.
- Standard-library `logging` with one formatter: readable lines in dev mode, JSON lines in production.

### Working method

- **Solo development on `main`.** Work is committed straight to `main` in small, self-contained commits and pushed. There are no pull requests for the maintainers' own work, and commits carry no tool attribution. Pull requests and the PR template are for outside contributors once the repository is public.
- **Checks run before every push.** pytest against Postgres, `ruff check`, `ruff format --check`, `pyright` in strict mode and `import-linter`. CI runs the same checks on every push, and `main` stays green.
- **The design moves with the code.** When implementation shows that a decision is wrong or incomplete, the same commit updates `README.md` and `plan.md`.
- **Spikes come first where a work package rests on an unverified assumption.** A spike is a throwaway script in `tmp/spikes/`, time-boxed to a day. Its findings go into `docs/spikes.md` before the dependent work package starts, because `tmp/` is not committed.

### Definition of done for a work package

1. The code and its tests are committed and pushed to `main`, and CI passes.
2. Tests sit in `tests/` for the core and in `plugins/<id>/tests/` for plugins, never beside the code.
3. Every new subdirectory has a short `README.md` in bullet form saying what it holds.
4. No function is longer than 150 lines, and deep nesting is split into helpers.
5. Public `teapot.sdk` names have docstrings.
6. Any design change is reflected in `README.md` and `plan.md`.
7. The work package's exit check, listed below, has been run and its result noted in the commit message.

## Setup before milestone 1

These steps need the maintainers, because they create accounts and secrets.

- [x] Create a private GitHub repository for the framework and push `main`. It stays private until milestone 7 releases it. Done: `hballington12/teapot`.
- [x] Create the **dev** Discord application and bot (D38). Turn on the Server Members intent. Leave Message Content off.
- [x] Create a test server and invite the dev bot with the `bot` and `applications.commands` scopes and Administrator.
- [x] Put the dev bot token in a local `teapot.env`, which `.gitignore` already excludes. It holds `TEAPOT_DISCORD_TOKEN` and `TEAPOT_DEV_GUILD_ID`.
- [x] Install Docker or Podman with Compose locally, for the dev Postgres. Done: Docker with Compose is installed.

## Spikes

Each spike answers questions that a work package depends on. The answers go into `docs/spikes.md`.

| Spike | Questions | Feeds |
|---|---|---|
| S1 asyncpg roles and protocol | Does `SET ROLE` on acquire with `RESET ROLE` on release behave under asyncpg's pool, and does the pool's own reset interfere? Which asyncpg calls use the extended protocol, given that `execute` without arguments uses the simple protocol? How do the helpers force one statement per call, and is a stacked `; RESET ROLE` refused? | WP1.3 |
| S2 advisory locks | Two-key `pg_try_advisory_lock(namespace, id)` for shards and `hashtext` for plugin ids. Shared against exclusive on the same key. Release on a killed connection. Reading them back from `pg_locks`. | WP1.5 |
| S3 raw commands and interactions | Registering command JSON with a bulk overwrite per guild without `CommandTree`. Handling every interaction in `on_interaction` without discord.py answering first. Whether an overwrite that keeps command names counts against the 200 creates per guild per day. | WP2.6, WP2.7, WP3.2 |
| S4 lazy members | `AutoShardedClient` with `chunk_guilds_at_startup=False` and suitable member cache flags. `query_members` limits and latency. Memory for a large guild that is not chunked. | WP1.7, WP4.2 |
| S5 MCP low-level server | The current `mcp` 2.x low-level server on Starlette: per-request tool lists from the bearer token, tool annotations, server instructions and transport security behind a proxy. | WP4.3 |

S1 and S2 run before milestone 1's database work. S3 and S4 run during milestone 1, and S5 runs during milestone 3.

## Milestone 1: skeleton

| WP | Scope | Depends on |
|---|---|---|
| 1.1 Workspace and tooling | Root `pyproject.toml` with the workspace, the `teapot` script and the `dev` group. Ruff, pyright and import-linter configuration. pytest with `pytest-postgresql`. The CI workflow. `template/compose.yaml` with a dev Postgres. Directory READMEs. | setup |
| 1.2 Settings and logging | `settings.py` with pydantic-settings and `teapot.env.example`. Logging setup and dev mode flags. | 1.1 |
| 1.3 Database layer | The owner, `teapot_app` and `teapot_plugins` roles and the `set_config` revoke in `teapot init`, the core and plugin pools, role switching on acquire with `RESET ROLE` on release, transaction handles, the open-block check, prepared-statement helpers and slow-transaction logging (D30, S1). | 1.2, S1 |
| 1.4 Migration runner | The `core` schema, plugin schemas and roles, one transaction per file, the `guild_id` check, the advisory lock, downgrade refusal, and core migration `0001` with `core.migrations`, `core.guilds`, `core.guild_plugins`, `core.jobs` and `core.processes` (D9). Later tables arrive as later core migrations in their own work packages. | 1.3 |
| 1.5 Locks and process rows | The lock connection, shard locks, plugin lock helpers, exit when the connection drops, and the informational process row (D40). | 1.3, S2 |
| 1.6 Work queue | Claims with `SKIP LOCKED` and leases, the computed shard filter, `NOTIFY` with `LISTEN` on the lock connection, the poll fallback, retries with back-off, lease reclaim, and the `maintenance` handler shell (D31). | 1.4, 1.5 |
| 1.7 App runner | `AutoShardedClient` with lazy member caching, uvicorn on `127.0.0.1`, the workers and the lock connection in one loop, `/healthz`, asyncio debug in dev mode, `teapot run` and a first `teapot plugins list`. | 1.6, S4 |

**Exit check.** `uv run teapot run` connects to the test server, and a second `teapot run` with the same token refuses to start. pytest, ruff, pyright and import-linter pass in CI.

## Milestone 2: actions and the interaction router

| WP | Scope | Depends on |
|---|---|---|
| 2.1 SDK types | `teapot.sdk` with `Risk`, `Surface`, `Actor`, `ActionSpec`, `Manifest`, `Plugin`, `Registrar`, the `*Ref` types, `LongText` and `UntrustedText`. The import-linter contract that plugins import only `teapot.sdk` (D45). | M1 |
| 2.2 Loader | Entry points or a given list, the id rules and reserved ids, duplicate ids, `TEAPOT_DISABLED_PLUGINS`, failure isolation, statuses and plugin locks (D14, D46). | 2.1 |
| 2.3 Registry and call path | Steps 1 to 8 for `READ` and `WRITE`, the default permission check, and member resolution with the REST fallback (D18, D19). | 2.2 |
| 2.4 Audit | Core migrations for `core.audit_log` and `core.audit_reads`, daily partitions through `maintenance`, the `post_audit` handler, and the log channel from the admin plugin's config (D24). | 2.3, 2.5 |
| 2.5 Config | Loading and validating `core.guild_plugins` config, and `ctx.config` (D10). | 2.2 |
| 2.6 Schema builder | One builder from input models to MCP JSON schema and Discord command JSON, with snapshot tests for every field type (D29). | 2.1, S3 |
| 2.7 Interaction router and renderer | Commands, components and modals, deferral, the `LongText` modal flow and the default embed renderer (D29, D32). | 2.3, 2.6, S3 |
| 2.8 Testing helpers | `teapot.testing` with guild, member and channel fakes, the `plugin_db` fixture and `invoke` (D45). The core's own tests switch to these fakes. | 2.3 |
| 2.9 First plugins | `teapot-announcements` with `post`, and `teapot-devtools` with a switch to fail in `setup`, a query against `core`, and a second package that declares the same id. | 2.4, 2.7, 2.8 |
| 2.10 Authoring guide | `docs/plugin-authoring.md` and the PR template. | 2.9 |

2.6 and 2.8 can run beside 2.3 to 2.5, because they only need the SDK types.

**Exit check.** The milestone 2 "done when" list in `plan.md`.

## Milestone 3: guild settings and the lifecycles

| WP | Scope | Depends on |
|---|---|---|
| 3.1 Admin plugin | `/plugins list`, `enable`, `disable` and `config`, and `/audit channel` and `recent`. | M2 |
| 3.2 Command sync | Global admin commands, per-guild hashes in a new `core.command_sync` migration, and `sync_commands` jobs that save the hash only on success (D32). | 3.1, S3 |
| 3.3 Plugin purge | `teapot plugins purge` with the exclusive lock, the confirmation prompt and the purge transaction (D7). | 3.1 |
| 3.4 Guild removal | Join and remove handlers, reconciliation at startup, the grace period and `purge_guild` (D49). | 3.1 |

**Exit check.** The milestone 3 "done when" list in `plan.md`.

## Milestone 4: tokens, MCP and the service API

| WP | Scope | Depends on |
|---|---|---|
| 4.1 Tokens | A `core.tokens` migration, issuing, checking and revoking, the `/tokens` commands, the bearer middleware, and the throttled `last used` update (D16, D17, D20). | M3 |
| 4.2 Admin lookups | `describe_guild`, `find_members` and `job_status` as `READ` actions (D25). | 4.1, S4 |
| 4.3 MCP adapter | The low-level server, per-token tool lists, annotations, server instructions, `UntrustedText` wrapping and transport security (D22, D23, D28). | 4.1, S5 |
| 4.4 Service API | `POST /api/v1/actions/<name>`. | 4.1 |

**Exit check.** The milestone 4 "done when" list in `plan.md`. The OAuth timing (open decision 2) is reviewed here.

## Milestone 5: the Tea clan's instance

| WP | Scope | Depends on |
|---|---|---|
| 5.1 Template | `template/` with `pyproject.toml`, `Dockerfile`, `compose.yaml`, `teapot.env.example` and the bare-metal files (D37, D43). | M4 |
| 5.2 Tea instance repo | A new repository made from the template, listing announcements, with the droplet's subdomain, Caddy block, Postgres, systemd unit and pgBackRest. | 5.1 |
| 5.3 Restore drill | A pgBackRest restore into a scratch cluster on another machine, written up in the instance repo's README. | 5.2 |

Needs the maintainers: the **production** Discord application, a DNS record for the subdomain, and a DigitalOcean Spaces bucket with keys for pgBackRest.

**Exit check.** The milestone 5 "done when" list in `plan.md`.

## Milestone 6: plan then apply

| WP | Scope | Depends on |
|---|---|---|
| 6.1 Plans | Canonical diffs and hashes, plan rows, confirm checks with the age limit, the `apply` handler with the unique index and progress (D21). | M4 |
| 6.2 Confirm everywhere | The Confirm button, and `confirm` on MCP and the service API through the same path. | 6.1 |
| 6.3 Plugins | `schedule` in announcements, and a `DESTRUCTIVE` action in devtools. | 6.2 |

Milestone 6 does not depend on milestone 5, so it can start once milestone 4 is merged.

**Exit check.** The milestone 6 "done when" list in `plan.md`.

## Milestone 7: open-source release

| WP | Scope | Depends on |
|---|---|---|
| 7.1 SDK 1.0 | Review of every public name, docstrings, the deprecation helper, and the import-linter contract across first-party plugins (D45). | M6 |
| 7.2 Scaffolding and init | `teapot new-plugin` and the complete `teapot init` (D43, D44). | 7.1 |
| 7.3 Self-hosting docs | `docs/self-hosting.md` and the template README. | 7.2 |
| 7.4 Project files | `LICENSE` once the licence is confirmed, `CONTRIBUTING.md`, `SECURITY.md`, the code of conduct and `CHANGELOG.md` (D48). | open decision 1 |
| 7.5 Release pipeline | A release workflow with PyPI trusted publishing for `teapot` and `teapot-announcements`, and a tagged template. | 7.4 |
| 7.6 Fresh-eyes test | Someone outside the project follows `docs/self-hosting.md` on a clean machine and writes a plugin with `teapot new-plugin`. Every point where they needed help becomes a fix. | 7.3, 7.5 |

**Exit check.** The milestone 7 "done when" list in `plan.md`. The repository then goes public.

## Critical path

```text
setup ─ S1 ─ 1.3 ─ 1.4 ─ 1.6 ─ 1.7 ─ 2.1 ─ 2.2 ─ 2.3 ─ 2.7 ─ 2.9 ─ 3.1 ─ 4.1 ─ 4.3 ─ 6.1 ─ 6.2 ─ 7.1 ─ … ─ 7.6
        S2 ─ 1.5 ──────┘               2.6 ─┘
```

- Milestone 5 runs beside milestone 6 and is off the critical path.
- The licence (open decision 1) must be settled before 7.4. It does not block anything earlier, because the repository stays private until then.

## Decisions made for implementation

These are settled here and do not need a design decision of their own.

- Python 3.12 as the floor and 3.13 for development (PEP 695 generics).
- Postgres 16 as the floor.
- Typer for the CLI, and standard-library logging.
- Spike findings live in `docs/spikes.md`, because `tmp/` is not committed.
- The earlier SQLite experiments in `tmp/cold-case-*` are superseded by the Postgres design and are not carried forward.

## Tracking

- Each work package is a GitHub issue named after its id, for example "WP1.3 Database layer", labelled `work package` and placed in its milestone, M1 to M7.
- Spikes are issues labelled `spike`, closed by the commit that adds their findings to `docs/spikes.md`. S1 to S4 sit in M1 and S5 in M3, where they run.
- The 42 issues (5 spikes and 37 work packages) were created from this document's tables. The commit that finishes a work package or spike closes its issue with "Closes #n".
- This document is updated when a work package is split, merged or reordered, so it stays the current plan.
