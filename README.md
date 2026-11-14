# teapot

An open-source framework for a general Discord bot built from plugins, in the spirit of Carl-bot. Anyone can run their own teapot for their own servers, write their own plugins for it, and grow it from one process to many. A hosted teapot, for people who just want a bot that works, is planned on the same code.

The Tea clan runs the first instance, on its droplet, and is the source of the first requirements. Staff use it through Discord slash commands, and LLM clients such as Claude Code use it through an authenticated MCP server.

To run your own teapot, follow [`docs/self-hosting.md`](docs/self-hosting.md); to write plugins for it, [`docs/plugin-authoring.md`](docs/plugin-authoring.md). The concrete build plan lives in [`docs/plan.md`](docs/plan.md), and the order of work in [`docs/implementation.md`](docs/implementation.md).

## Goals

- An Apache-2.0 framework that anyone can self-host, with first-party plugins, a stable plugin SDK and a template for new instances (D41 to D48).
- One long-running Python process to begin with, with Postgres beside it and a reverse proxy in front. The same code scales out to several processes and hosts when one is no longer enough (D40).
- A small core that holds the Discord connection, the database, plugin config, tokens and permissions, a durable work queue and an audit trail.
- Plugins provide every feature. Whoever runs an instance decides which plugins it runs, including ones they wrote themselves. A plugin hub may list plugins later.
- Three ways in:
    - Discord slash commands for members (interacting with what staff set up) and for staff (control).
    - An MCP server over HTTPS, so an LLM can do admin work for a staff member in a server that person is authorised for.
    - A service API for other programs, such as an event backend that pings a team when something happens.
- The bot holds near-Administrator power in every server it joins. Safety comes from the plugin protocol, the permission checks and the audit trail.
- Over time, plugins replace a server's dependence on other bots (Carl-bot, MEE6 and similar).

## Pain points it addresses

- **Bulk work hits rate limits.** Changing roles on hundreds of members takes hundreds of separate requests. An LLM making one tool call per member is slow, costly and hard to review.
- **Event setup and teardown repeat.** Team roles, team channels, permission overwrites, feed channels and captain roles are made for every event and archived afterwards. Past event bots rebuilt the same roster and role-gate code each time.
- **Discord has hard caps.** 250 roles and 500 channels per server, and 50 channels per category. Long-lived event channels hit these unless they are archived.
- **Moderation needs a trail.** Joins, leaves, kicks, bans and deleted messages need recording. With an LLM acting for staff, the trail must also say which human asked for each action.
- **Several bots overlap.** Each has its own config, dashboard and permission model, and staff have to know which bot does what.
- **Identity across game and Discord is messy.** Mains, alts, RSN changes, and clan membership that only partly overlaps with Discord membership. That plugin is out of scope for now, and the core must not make it harder later.
- **Timezones vary.** Timers, giveaways and event starts are stored in UTC and shown as Discord timestamps.
- **Multi-server needs isolation.** An action in one server never touches another. A staff member in server A has no rights in server B. A server's admins can switch off any plugin.
- **Plugins come and go.** A plugin's tables, config and jobs must survive being disabled, survive an upgrade that changes their shape, and be removable completely when the plugin is gone for good.
- **Growth must not force a rewrite.** Bots that start small and succeed end up rebuilding their storage and sharding. teapot makes the choices that scale before the first plugin is written.
- **Hosted bots are closed.** A server that outgrows a hosted bot's features has nowhere to go. With teapot, the same bot can be self-hosted and extended.

## Decisions

The design targets a framework that many people run and that grows to many servers and large member counts, starting from the Tea clan's instance. The **operator** in these decisions is whoever runs an instance: the Tea clan for its own, any self-hoster for theirs, and the teapot maintainers for the hosted service. Work that only a later need calls for is listed under deferred work in [`docs/plan.md`](docs/plan.md#deferred-work), with the trigger that brings it in.

### Architecture

1. **One action registry with several front doors.** A plugin registers actions, each with a typed input model, a required permission and a risk level. Slash commands, MCP tools and the service API are thin adapters over that registry. Every call goes through the same permission check and audit log, including the core's own tools.
2. **Everything is scoped to one server.** Every action runs with a context for a single server, and the plugin API hands out nothing that reaches across servers. Every plugin table carries a `guild_id` column, which the migration runner checks (D9), and so does every core table that holds a server's data. Bookkeeping tables such as `core.migrations` hold none. Plugin config is stored per server.
3. **Installing a plugin and enabling it are separate steps.** The operator installs plugins, which is the trusted, code-reviewed step. Each server's admins enable and configure the installed plugins they want. A plugin's commands appear only in servers where it is enabled. The full lifecycle is D7.
4. **Plugins are Python packages found through entry points and pinned in the instance's lockfile.**
    - The loader loads every installed package that declares a `teapot.plugins` entry point. Nothing checks a signature or asks the teapot maintainers, so an operator can run plugins they wrote themselves (D44).
    - A plugin can be a package inside the instance's own repo, a git dependency pinned as `git+<repo>@<commit>`, or a release from PyPI. The instance's `uv.lock` records the hashes of all of them.
    - An update bumps the pin, and the operator reviews the diff between the old and new versions. This is the RuneLite Plugin Hub model, where a plugin is a repository and a pinned commit, and the lockfile plays the part of the hub's signed manifest. A future plugin hub is a catalogue of such pins.
5. **Plugins run in the bot's process with no sandbox.** The operator trusts the plugins they install, so the operator's code review is the security boundary, as it is on the RuneLite Plugin Hub. The database roles of D9 catch mistakes, and they do not replace review. Because nothing is sandboxed, the hosted service runs only plugins the teapot maintainers have reviewed (D47).
6. **The protocol holds what current plugins use, and grows by addition.**
    - From the start a plugin can declare:
        - actions, which become slash commands, MCP tools and service routes, on all three front doors unless the action narrows its surfaces
        - modals for multi-line `LongText` input (D29)
        - Discord event hooks (join, leave, message, reaction)
        - scheduled jobs
        - a config model (D10) and its own tables with migrations (D9)
        - the permissions its actions require
    - Added when a plugin needs them: buttons and select menus, dependencies on other plugins, autocomplete, context-menu commands, voice hooks, MCP resources, HTTP routes, a per-member store, a hook for deleting a member's data (D11) and a machine-readable list of external hosts (D12).
    - Each addition is a manifest field with a default or an optional protocol detected with `hasattr`, so existing plugins keep working without changes. The protocol is published as `teapot.sdk` (D45).

### Plugins and data

7. **A plugin has six lifecycle steps, and its data is kept until it is purged.**
    - The operator installs, upgrades, uninstalls, blocks and purges. Server admins enable and disable.
    - Disabling, uninstalling and blocking keep the plugin's schema, config and jobs. A reinstall carries on where it left off.
    - A plugin a process has not loaded, whether blocked, uninstalled or failed, has one status with a reason. It keeps its data and cannot be enabled. Each process reports its statuses through `/healthz` and `/plugins list`, and holds a shared advisory lock for each plugin it loaded (D40).
    - Purging is the only step that deletes data, and it is an operator CLI command (D34), because it cannot be undone and affects every server. It runs while the bot is up, and refuses unless it can take that plugin's lock exclusively, which fails while any process has the plugin loaded.
    - What each step does is tabled in [`docs/plan.md`](docs/plan.md#plugin-lifecycle).
8. **Plugin data lives in config and in the plugin's own tables.**
    - **Config** is what a server's admins set: channels, durations, role choices. It is one Pydantic model per plugin and server, stored as JSONB (D10).
    - **Own tables** hold everything the plugin writes itself: giveaway entries, posted message IDs, moderation records. Data that needs queries such as leaderboards needs tables anyway, and a single row of plugin state is a one-row table.
    - A per-member store in the style of Red-DiscordBot's `Config` API can come back by addition if several plugins end up writing the same small per-member tables.
9. **Each plugin owns a Postgres schema and role, and changes it with forward-only numbered SQL migrations.**
    - Plugin `x` gets the schema `plugin_x` and the role `teapot_plugin_x`. The role can create and use objects in its own schema and nothing else. It has no rights on the `core` schema or on other plugins' schemas, so a stray query or foreign key into another plugin fails at once.
    - Plugin code reaches Postgres through its own pool, logged in as `teapot_plugins`, a role with no rights of its own that is a member of every plugin role. `EXECUTE` on `set_config` is revoked from `PUBLIC`, and the `ctx.db` helpers send every statement as a prepared statement, which runs exactly one statement per call. An SQL injection bug in a plugin therefore cannot change the role, and cannot reach `core`, where token hashes live. Reaching another plugin would need that plugin to run dynamic SQL built from untrusted input in a plpgsql function, which the authoring guide forbids and review checks. This matters most for third-party plugins (D44). Spike S1 in [`docs/spikes.md`](docs/spikes.md) has the evidence.
    - Each plugin ships `migrations/0001_<name>.sql`, `0002_<name>.sql` and so on. `core.migrations` records the applied version per plugin, and each plugin's history is independent of every other.
    - A plugin's migrations run as its role, with `search_path` set to its schema. Each file runs as one script inside its own transaction, which Postgres supports for every DDL statement used here, so a failed migration leaves nothing half applied. The script is sent whole, so functions and triggers with dollar quoting work.
    - Before the transaction commits, the runner checks that every table in the plugin's schema has a `bigint` column named `guild_id`. A table without one fails the migration. This is what lets the core delete a server's data with no plugin code (D49).
    - The core's tables live in the schema `core` and use the same runner.
    - Migrations only go forward. Keeping the previous release of the plugin working (add first, remove in a later release) is recommended now, and becomes required when shard clusters arrive, because only then do two releases run against one schema (D15). A self-hoster who skips releases gets every file in order.
    - Purge is `DROP SCHEMA plugin_x CASCADE` and `DROP ROLE teapot_plugin_x`, so it needs no plugin code.
    - This replaces Alembic, whose shared revision graph breaks once an uninstalled plugin's scripts are gone.
10. **Config models evolve through Pydantic alone.**
    - New fields get defaults.
    - Renamed fields keep reading old data through `validation_alias=AliasChoices("new", "old")`.
    - Removed fields are ignored with `extra="ignore"`.
    - A reshape that none of these cover goes in a `model_validator(mode="before")`.
    - Config is saved back in the new shape the next time it is written. Plugin tests keep stored samples from earlier versions and check that they still validate.
11. **Deleting a member's data arrives with the first plugin that keeps it.** No plugin keeps per-member data yet. When the first one does, `teapot users delete` and a `delete_user_data` plugin hook, as in Red-DiscordBot, land together. Discord's developer policy expects bots to honour deletion requests, and the hosted service (D47) needs this from the start.
12. **External connections are declared for review.** Every plugin's README has an "External connections" section listing each host it contacts, and the PR template asks for it. The reviewer checks the list against the code. The hosted service moves the list into the manifest, adds RuneLite-style consent at enable time and adds an HTTP client that refuses undeclared hosts.
13. **The operator can block a plugin everywhere.** Listing it in `TEAPOT_DISABLED_PLUGINS` in `teapot.env` and restarting stops it in every server, keeps its data and refuses enabling until it is removed from the list. This plays the part of RuneLite delisting a plugin.
14. **A broken plugin never takes down the bot.**
    - A plugin that fails to import, fails `setup` or fails a migration is not loaded, with the reason `failed`. Everything else starts. `/healthz`, `/plugins list` and the operator CLI show the failure.
    - A plugin released outside the teapot monorepo declares its compatible SDK in its `pyproject.toml`, for example `teapot>=1.2,<2`, and uv refuses to lock an incompatible combination, so a mismatch shows up before any deploy. First-party plugins are released together with the core and pin it exactly.
15. **Installs and migrations happen at restart.** Reloading Python packages inside a running process is fragile, and installs are rare and already reviewed. A starting process takes a Postgres advisory lock and runs pending migrations, so processes starting together migrate once. A one-process instance stops, migrates and starts. Rolling restarts arrive with shard clusters, together with the migration rule of D9 that makes them safe. Per-server enable and disable take effect at once.

### Tokens and permissions

16. **Every token acts as the member who created it.**
    - A token looks like `teapot_<token id>_<secret>`, after GitHub's token format. The id finds the row directly, and the prefix lets secret scanners spot leaked tokens.
    - The secret is long and random, so it is stored as a SHA-256 hash. Password hashes such as bcrypt are built for low-entropy secrets and are not needed.
    - A member creates tokens with `/tokens create` in a server. A token is shown once, expires, and can be revoked. Rotating is revoking and creating.
    - Each call checks the creator's live permissions (D18), so a token never holds more than its creator, and every audit row names a human.
    - An event backend uses a token made by a staff member and narrowed to the actions it needs (D20). If that member loses their staff role, the token stops working under the same rule as D18, and a new one is issued.
    - Claude Code connects with `--header "Authorization: Bearer teapot_..."`. OAuth 2.1 can come later as a second way to issue the same token row, once claude.ai or the desktop app need access.
17. **Tokens carry a maximum risk.** Risks are ordered (`read` below `write` below `destructive`), and each token holds the highest risk it may use. New tokens default to `write`, so `destructive` is always an explicit choice. A monitoring token can be read-only whatever its creator's roles allow, and the check is one comparison.
18. **Permission is checked live on every call.** Each call checks the member's current roles in the server, from the bot's member cache with a REST fetch when the member is not cached (D25). Removing a staff role ends access at once, for slash commands and tokens alike.
19. **The bot's own check is authoritative.** Each action declares a default requirement in Discord permissions (for example Manage Roles for role actions), and the core checks it against the member's current permissions. Slash commands also set `default_member_permissions`, which only controls who sees them in the Discord UI. Per-server overrides that remap an action to chosen roles come later, likely when event captains need to post in team channels. The call path keeps a place for them.
20. **Each token is bound to one server and can be narrowed to chosen actions.**
    - The token decides the server, so no tool or route takes a guild id. An LLM cannot target the wrong server, and text injected from one server cannot steer actions in another.
    - A staff member who works in two servers holds two tokens.
    - A token may carry an allow-list of action names. A Battleships backend's token could allow only `battleships.post_feed`, and that action reads its feed channel from the plugin's config, so the backend posts there and nowhere else.

### Safety

21. **Bulk and destructive actions use plan then apply, and the plan is its audit row.**
    - Called without a `confirm` value, a destructive action returns a summary of the diff (add 12, remove 3, skip 4 above the bot's role, with a page of entries) and a confirm value. Deletes, bans and mass removals always take two steps.
    - The plan's audit row stores the action, the input, a hash of the canonical diff and the confirm value, which is random. Nothing is kept in memory, so any process can apply any plan.
    - To apply, the client calls the same action again with `confirm`. It is an ordinary call, so permission is checked again. The core finds the plan row and refuses unless the actor, guild, action and input match, the plan is younger than 15 minutes, and a freshly computed diff has the stored hash. A changed target refuses the apply, and the response carries the fresh plan. Terraform refuses stale saved plans for the same reason.
    - The apply's audit row points at the plan's row, so the trail links each change to the plan a human saw.
    - An apply runs as a job on the work queue (D31) and reports progress. discord.py already waits out per-route and global rate limits, and the queue runs at most one apply per server at a time.
    - The LLM is responsible for judging whether a plan is correct. The MCP server's instructions and every destructive tool description always tell the LLM to show the plan to its user and get their agreement before applying it.
22. **Risk levels map onto MCP tool annotations.** `readOnlyHint` and `destructiveHint` come from each action's risk, so clients can run their own confirmation prompts.
23. **Member-written text is marked as untrusted.** Message content, nicknames and other text written by members is wrapped in an explicit untrusted marker in every MCP tool output. Together with plan then apply (D21), maximum risk (D17) and single-server tokens (D20), this limits prompt injection through server content.
24. **Every action is logged, and changes are posted.**
    - A `WRITE` or `DESTRUCTIVE` action gets its audit row before it runs, with the outcome `started`, the member who asked, the token if any, the front door, the action and its input. A crash halfway through a side effect therefore leaves a trace. After the action, one transaction records the outcome and queues a `core.post_audit` job, which posts the row to the server's log channel. A Discord outage delays posts and never loses them.
    - A `READ` action has no side effects, so it gets a single row after the call and is never posted. An LLM session's lookups then cost one write each and do not flood the log channel.
    - An action's own database writes happen in its own short transactions (D30), so they are not atomic with the audit row. The `started` row covers that gap.
    - `READ` rows go to `core.audit_reads`, partitioned by day and kept for 30 days by default. Old partitions are dropped whole, so the high-volume table never needs batch deletes. Every other row goes to `core.audit_log`, a plain table kept for a year by default and trimmed by a batched delete, which its low volume keeps cheap.
25. **Reads come from the cache, and the cache stays small.**
    - Guilds, channels and roles are always cached. Members are cached when they appear in events or are fetched, and the bot never downloads full member lists at startup. A server with 100,000 members then costs memory only for the members who are active.
    - A permission check for an uncached member fetches it over REST (D18), and then caches it.
    - Member search uses Discord's own search through the gateway, so it works without a full member list.
    - MCP tools return compact summaries with paging instead of dumping members.
26. **The bot's role sits below the owner and senior staff roles.** The setup docs say so. Discord's role hierarchy then stops the bot editing those roles, even with Administrator.

### Stack

27. **`discord.py`** is the Discord library, used through `AutoShardedClient` from the start. It runs as one shard below 2,500 servers and adds shards by itself above that. discord.py's own extensions system and command tree are not the plugin protocol. The core handles interactions itself (D32).
28. **The official `mcp` Python SDK over streamable HTTP**, through its low-level server, on Starlette and uvicorn in the same asyncio loop as the Discord client.
    - The low-level `on_list_tools` and `on_call_tool` handlers take JSON schemas straight from the Pydantic models, and the tool list is filtered per token. FastMCP has no easy way to filter the list per caller.
    - A Starlette middleware checks the bearer token on `/mcp` and the service API.
    - The SDK's DNS-rebinding protection is configured with the public hostname, because the reverse proxy forwards it.
29. **Pydantic models define action inputs, action outputs and config, and the core builds Discord's command payloads from them.**
    - One schema builder turns an input model into both the MCP tool schema and Discord's application command JSON, so the two cannot drift apart. The core registers the JSON with Discord directly. discord.py's `CommandTree` is not used, so no synthetic signatures are needed.
    - Input fields are limited to a fixed set of types: `str`, `LongText`, `int`, `bool`, `Literal` and the `*Ref` types, each optional or not. Raw interaction data carries options as plain values and IDs, which is exactly what the `*Ref` types hold.
    - `LongText` holds multi-line text, which slash options cannot. A slash command with a `LongText` field opens a modal for it, and the action runs once the modal is submitted.
    - Outputs go back as JSON over MCP and the service API. The slash adapter renders them as an embed of the model's fields by default, and an action may supply its own renderer.
30. **Postgres through `asyncpg`, with raw SQL and short explicit transactions.**
    - Migrations already define the schema in SQL, so an ORM would describe it a second time.
    - Each process holds two pools: one logged in as `teapot_app` for the core, and one as `teapot_plugins` for plugin code (D9). A plugin connection switches to the plugin's role when it is acquired and runs `RESET ROLE` when it is released, because asyncpg's own reset leaves the role in place. A single read needs no transaction.
    - Writes go through `async with ctx.db.transaction() as tx:` blocks, and everything inside a block goes through `tx`, including `tx.schedule(...)` to queue a job in the same transaction. Pyright checks the handle, and nothing is routed implicitly.
    - Calling `ctx.db` inside an open block raises an error, because it would use another connection and miss the block's own writes. A context variable marks open blocks for this check only.
    - A transaction block never awaits Discord or HTTP, so no action holds a connection and its row locks across a slow call. Dev mode logs any block held longer than 100 ms.
31. **One durable work queue in Postgres.** Every job is a handler and a payload with a run time, a state, retries and progress. Plugin timers and scheduled pings use it, and so do the core's own handlers for plan applies (D21), audit posts (D24), command syncs (D32) and server data removal (D49).
    - Workers claim jobs with `SELECT ... FOR UPDATE SKIP LOCKED`, so any number of workers in any number of processes share the queue without double runs.
    - `NOTIFY` wakes workers when a job is due now. Each process listens on its lock connection (D40), so the wake-ups need no connection of their own, and a poll every five seconds catches any notification lost while that connection reconnects.
    - A process that runs only some of the shards claims only jobs whose `(guild_id >> 22) % shard_count` falls on its shards, which keeps a job beside the cache it needs. The shard is computed in the claim query and never stored, so resharding cannot leave stale values. A process that runs every shard skips the filter.
    - Jobs are picked back up after a restart.
32. **One interaction router handles every command, button, select menu and modal.**
    - Slash commands are routed by command and subcommand name, and components by custom IDs of the form `teapot:<plugin id>:<handler>:<payload>`. Because no state is held in memory, buttons keep working after a restart and in any process.
    - Buttons and select menus are used in place of reactions for role picks and giveaway entry. They are tied to IDs the bot controls and are easier to audit. Simple polls can use Discord's native polls.
    - A plan's Confirm button is an ordinary component whose payload is the plan's confirm value, so slash commands, MCP and the service API share one confirm path (D21).
    - Each plugin's command group is registered per server, only where the plugin is enabled. The core keeps a hash of each server's command set and syncs only servers whose hash changed, as queue jobs paced within Discord's limits. The hash is saved after a sync succeeds, so a failed sync is retried. A plugin upgrade that touches thousands of servers then spreads over minutes and never blocks startup.
33. **Plugins never block the event loop.** One loop serves the Discord gateway and the MCP server, so blocking I/O in a plugin stalls both. The authoring guide requires async I/O, and dev mode turns on asyncio's slow-callback detection so offenders show in the logs.
34. **A uv project with one entry point.** `uv run teapot run` starts a bot process. The other subcommands are the operator CLI for work that belongs outside Discord: setting up an instance (D43), listing plugins and their state, purging a plugin and scaffolding a new one (D45). The CLI works on the database alone, and reads the advisory locks in `pg_locks` to see what is loaded (D40). Tests live in `tests/` and run with pytest against a real Postgres. Ruff for linting and formatting, and pyright in strict mode, because types are part of the safety net.

### Hosting and operations

35. **teapot runs as independent instances.** Each instance has its own Discord application, token, database and config, and its own operator. The Tea clan's instance, any self-hoster's instance and the hosted service (D47) are all instances of the same framework. Separate applications keep rate limits, Discord verification and intent reviews of one instance away from every other.
36. **HTTPS at the edge and plain HTTP only between the reverse proxy and the bot.** The proxy terminates TLS and forwards `/mcp` and `/api` to a `127.0.0.1` port. Every client uses the public HTTPS URL, so there is one path to secure and log. `/healthz` is not forwarded, because it lists the installed plugins. Deploy scripts call it on localhost.
37. **The Tea clan's instance follows the droplet conventions** (`events` skill, `references/hosting.md` in `hballington12/tea-skills`). It is the bare-metal example in the instance template (D43):
    - code in `/opt/teapot`, set up with `uv sync --frozen --no-dev`
    - secrets in `/etc/teapot/teapot.env`
    - Postgres from the distribution packages, listening on a Unix socket only, with memory settings sized for a shared droplet
    - Caddy as the reverse proxy
    - a hardened systemd unit
    - a deploy script that restarts the bot, which runs migrations, and ends with a health check
    - pgBackRest archiving WAL continuously to DigitalOcean Spaces, with weekly full and daily differential backups and its own retention, so a lost droplet costs seconds of data
38. **Development uses a separate dev bot application and a test server**, so experiments never touch a live server. The whole stack runs locally against Postgres from the template's Compose file, and Claude Code connects to the local MCP URL with a dev server token.
39. **Plan for verification early.** Turn on the Server Members intent, which joins, leaves and member updates need. Turn on Message Content only if a plugin needs message text. A bot must be verified by Discord before it can join more than 100 servers, and verified bots need approval for privileged intents. Large self-hosted instances meet this too, and the setup docs say so.

### Scale

40. **Process memory holds only caches and work in flight. Everything that must be right across processes lives in Postgres.**
    - Plans, confirm buttons, jobs, plugin config, tokens and command-set hashes are all rows. No correctness depends on which process handles a request.
    - Ownership is held as Postgres session advisory locks on one dedicated connection per process. A process takes an exclusive lock for each shard it runs and a shared lock for each plugin it loads.
    - A second process on the same bot token fails to take its shard locks and refuses to start. Two processes on one token would otherwise both handle every event. Purge takes a plugin's lock exclusively, which fails while any process has the plugin loaded (D7).
    - A crash or a dropped connection releases the locks at once, so no staleness rule is needed. A process whose lock connection drops exits, and its supervisor restarts it.
    - Each instance has its own database (D35), so the locks only see processes of the same instance. With separate databases nothing can detect two processes on one token, so D38's separate dev application is the guard there, and the setup docs state it.
    - Each process also writes an informational row with its host, shards and version, for `teapot plugins list` and later for routing between clusters. Nothing correct depends on it.
    - The first deployment is one process with all shards. When one process is no longer enough, shards split into clusters of several processes, each owning the servers that Discord's formula `(guild_id >> 22) % shard_count` gives it. Plugins need no changes for that step. Its shape is under deferred work.

### Open source and distribution

41. **teapot uses a permissive licence, with Apache-2.0 the leading choice.** The core, the SDK, the first-party plugins and the instance template all share it. Apache-2.0's explicit patent grant suits a framework that companies may build on, and MIT or BSD-2-Clause remain the alternatives until it is confirmed (open decision 1 in the plan). Third-party plugins choose their own licence.
42. **The framework and the instances are separate projects.**
    - This repository is the framework. It holds the core, the SDK, the first-party plugins, the instance template and the docs, and it publishes `teapot` and each `teapot-<plugin>` to PyPI.
    - An instance is a small project made from the template: a `pyproject.toml` that lists the plugins it runs, a `uv.lock`, an env file and deploy files. The Tea clan's instance is one such repo, and the hosted service is another.
    - Choosing plugins, pinning them and reviewing their updates happen in the instance, which is where D4 belongs.
43. **The instance template supports both a quick and a careful setup.** It ships a Docker Compose file with the bot and Postgres, for anyone who wants a working bot in minutes, and the Tea droplet's bare-metal files as a second example (D37). `teapot init` creates the database roles, generates the secrets in the env file and prints the Discord application settings to use. The README walks through creating the Discord application, the intents to turn on, and the rule of one teapot per server.
44. **Anyone can write plugins for their own instance without approval from the teapot maintainers.** A plugin is a package with a `teapot.plugins` entry point, kept inside the instance's repo, in its own repo or on PyPI. The operator who installs it is the one who reviews it. The maintainers' review applies only to the hosted service's catalogue (D47) and to listings in a future plugin hub.
45. **Plugins build against `teapot.sdk`, which follows semantic versioning.**
    - `teapot.sdk` holds everything a plugin uses: the protocol types, `ActionContext`, the `*Ref` and `LongText` types and the registrar. Everything else in `teapot` is internal and may change in any release.
    - `teapot.testing` provides guild and member fakes and a Postgres fixture that runs a plugin's migrations, so plugin authors test the way the core does.
    - `teapot new-plugin <id>` scaffolds a package with its entry point, manifest, first migration, README with an "External connections" section, and tests.
    - A breaking change to `teapot.sdk` needs a major version, and the old form keeps working with a deprecation warning for at least one minor release first.
46. **Plugin ids are unique within an instance.**
    - An id matches `[a-z][a-z0-9_]{1,31}`, which fits Discord's command names and the Postgres schema and role names of D9.
    - The ids `core`, `admin`, `teapot` and `plugin` are reserved, as are `plugins`, `audit` and `tokens`, the admin plugin's command groups.
    - When two installed packages declare the same id, the loader loads neither and names both packages in the error. A local `giveaways` plugin and a later first-party one therefore never share a schema or a command group by accident.
    - A future plugin hub reserves ids across its listings.
47. **The hosted service is an instance run by the teapot maintainers.** Server admins sign up by adding its bot, and they enable plugins from a catalogue of plugins the maintainers have reviewed. Custom plugins need a self-hosted instance, because plugins are not sandboxed (D5). Before it opens, the hosted service needs the deferred work for strangers sharing one instance: per-server quotas and fair queue claims, OAuth (D16), member data deletion (D11), egress consent and enforcement (D12), and a privacy policy and terms of service for Discord verification.
48. **The repository carries the files an open-source project needs.** `LICENSE`, `CONTRIBUTING.md`, `SECURITY.md` with a private disclosure address, a code of conduct, a changelog kept per release, and release notes that call out any manual step for operators.
49. **When the bot leaves a server, that server's data is deleted after a grace period.**
    - On the guild-remove event, the core records the time and queues a `purge_guild` job 30 days later. If the bot is added back before then, the job is cancelled and everything is as it was.
    - The job deletes the server's rows from every core table and from every plugin table, using the `guild_id` column that D9 requires. No plugin code is needed.
    - The grace period is a setting, so an operator can shorten it. Discord's developer policy expects bots to delete data they no longer need.

### First milestone

50. **The first plugin is an announcements proof of concept.** It posts an embed to a channel, and it exercises a slash command with a `LongText` body, an MCP tool, a service-API call, the permission check and the audit log.
