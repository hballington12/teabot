# Spike findings

Findings from the spikes in [`implementation.md`](implementation.md#spikes). The spike scripts are throwaway and live in the uncommitted `tmp/spikes/`, so this file is the record. Each section ends with what changed in the design.

## S1 asyncpg roles and protocol

Run on 2026-11-13 against Postgres 16.16 and asyncpg 0.30, with a core table, two plugin schemas and their roles.

### Pool reset

- asyncpg's pool runs `SELECT pg_advisory_unlock_all(); CLOSE ALL; UNLISTEN *; RESET ALL;` when a connection is released.
- `RESET ALL` resets `search_path`, and does **not** reset the role. A connection released after `SET ROLE teapot_plugin_x` came back from the next acquire still as `teapot_plugin_x`.
- The reset releases every advisory lock the connection holds, and drops every `LISTEN`.

Consequences:

- Releasing a plugin connection must run `RESET ROLE` explicitly.
- The lock connection of D40 must stay outside any pool, or its shard and plugin locks and its `LISTEN` would vanish on release. The plan already said so, and this confirms it.

### Query protocol

- `execute` without arguments uses the simple query protocol, and runs several statements: `execute("SELECT 1; SELECT 2")` succeeded.
- `execute` with arguments, `fetch`, `fetchrow`, `fetchval` and `prepare` use the extended protocol, and refuse a second statement with "cannot insert multiple commands into a prepared statement". This holds even without arguments.
- A prepared statement's `get_statusmsg()` returns the command tag, such as `INSERT 0 1`. A helper can therefore run every statement through `prepare` and still report row counts.

Consequence: the `ctx.db` and `tx` helpers send every statement through a prepared statement, never through argument-less `execute`.

### Escaping the plugin role

With the connection logged in as `teapot_app` and switched to `teapot_plugin_x`:

| Attempt | Result |
|---|---|
| Read `core.tokens` or another plugin's table directly | refused: permission denied for schema |
| Injected `UNION SELECT ... FROM core.tokens` | refused: permission denied for schema core |
| Injected stacked `; RESET ROLE; SELECT ... FROM core.tokens` through `fetch` | refused: multiple commands |
| The same through argument-less `execute` | **succeeded**, role back to `teapot_app` |
| Injected single expression `set_config('role', 'teapot_app', false)` through `fetch` | **succeeded**. The role changed for every later statement on the connection, and the next query read `core.tokens`. `set_config('role', 'teapot_plugin_y')` reached the other plugin's data the same way |
| `set_config` and a read of `core` in the same statement | refused. The new role only applies from the next statement |

The design's claim that one statement per call makes the role a hard limit for SQL injection (D9) was therefore false. A single injected expression escapes.

### Closing the escape

- Revoking `EXECUTE` on `pg_catalog.set_config(text, text, boolean)` from `PUBLIC`, and granting it back to `teapot_app`, refused the injected `set_config` with "permission denied for function set_config". Plugin reads, writes and `RETURNING` kept working, and `teapot_app` could still call `set_config`.
- One route remained. A plpgsql function in the plugin's own schema that runs dynamic SQL (`EXECUTE sql`) could still run `SET ROLE teapot_app`, because `SET ROLE` is checked against the session user, and the session user was `teapot_app`.
- With the plugin connection logged in as a separate session user `teapot_plugins`, which has no rights of its own and is only a member of the plugin roles, the same function was refused `SET ROLE teapot_app`. It could still switch to another plugin's role that `teapot_plugins` is a member of.

### Queuing jobs from a plugin role

- Inside a `SECURITY DEFINER` function, `current_user` is the function's owner, so the planned `core.schedule_job` could not tell which plugin called it.
- A function `plugin_x.schedule_job(guild_id, handler)` owned by `teapot_app`, `SECURITY DEFINER`, with `SET search_path = core, pg_temp` and the plugin id written into its body, worked:
    - plugin `x` queued a job through it, and the row carried the plugin id `x`
    - plugin `x` still could not read `core.jobs`
    - plugin `x` could not replace the function, because it does not own it

### Design changes from S1

- **Two session users (D9, D30).** The core's pool logs in as `teapot_app`. Plugin code uses a second pool that logs in as `teapot_plugins`, which has no rights of its own and is a member of every plugin role. A plugin connection runs `SET ROLE` and sets `search_path` on acquire, and `RESET ROLE` on release.
- **`set_config` is revoked from `PUBLIC`** and granted to `teapot_app` and the owner. `teapot init` does this. It needs a superuser once. On managed Postgres without a superuser, `teapot init` warns, and the injection limit falls back to review.
- **Helpers use prepared statements only.**
- **What the role now guarantees.** An SQL injection bug in a plugin cannot reach `core`, where token hashes live, and cannot change the role through `set_config`. Reaching another plugin needs a plpgsql function in that plugin which runs dynamic SQL built from untrusted input. The authoring guide forbids that, and review checks it.
- **Per-plugin `schedule_job`.** The migration runner creates `plugin_<id>.schedule_job` for each plugin, owned by `teapot_app`, with the plugin id built in, and grants `EXECUTE` only to that plugin's role. `core.schedule_job` is dropped from the design.

## S2 advisory locks

Run on 2026-11-13 against Postgres 16.16, with plain connections outside any pool.

| Check | Result |
|---|---|
| A takes `pg_try_advisory_lock(7001, 0)`, then B tries the same key | A true, B false |
| A takes the same key again in the same session | true. Advisory locks are re-entrant per session |
| A's backend is terminated with `pg_terminate_backend` | A's connection is closed, asyncpg's termination listener fires, and B then gets the lock at once |
| Two connections take `pg_try_advisory_lock_shared(7002, key)` for one plugin | both true |
| A third tries the same key exclusively, as purge would | false while either shared lock is held, true once both are released |
| A connection tries the shared lock while purge holds it exclusively | false |
| `LISTEN teapot_jobs` on the lock-holding connection, with `pg_notify` from another connection, inside and outside a transaction | both notifications arrived, and the lock stayed held |

`pg_locks` shows the two-key form as `classid` (the namespace), `objid` and `objsubid = 2`, with `mode` `ExclusiveLock` or `ShareLock`. `objid` is an `oid`, so a negative key appears as its unsigned value: the key `-1405399493` showed as `2889567803`.

### Design changes from S2

- **Plugin lock keys are computed in Python** as the first four bytes of the SHA-256 of the plugin id, read as a signed 32-bit integer. Postgres's `hashtext` is internal and not promised to stay the same across major versions, so it is dropped from the design.
- **Reading locks back** converts `objid` from unsigned, and maps keys to plugin ids by hashing the known ids.
- **A dropped lock connection** is detected with asyncpg's termination listener, which makes the process exit (D40).
- **Re-entrancy confirmed.** Two workers sharing one session could both take the same advisory lock, so the one-apply-per-guild rule stays a unique index (D31).

## S3 raw commands and interactions

Run on 2026-11-13 with discord.py 2.7.1 against the dev bot and the test server.

| Check | Result |
|---|---|
| Register a guild command with `http.bulk_upsert_guild_commands`, no `CommandTree` | worked |
| Overwrite again with the same name and a changed description | the command keeps its id (`1570837903481896980`), and only `version` changes |
| List after the overwrites, then overwrite with `[]` | one command, then none |

- An overwrite that keeps a command's name updates it in place. Discord's limit of 200 command creates per guild per day counts new commands, so syncing an unchanged or edited command set does not use it up. Adding or renaming a command does. The per-guild sync of D32 therefore costs nothing against that limit for ordinary plugin upgrades.
- discord.py's `ConnectionState.parse_interaction_create` hands application commands to a `CommandTree` only when one is attached, and components and modals to its view store, which finds nothing when no views are registered. It then dispatches the `interaction` event for every interaction. A client with no tree and no views receives every interaction in `on_interaction`, and nothing answers before the core does.
- A bot cannot invoke its own slash commands, so receiving a live interaction is confirmed in WP2.7's exit check, with a person running the command in the test server.

### Design changes from S3

None. D29 and D32 hold as written.

## S4 lazy members

Run on 2026-11-13 with discord.py 2.7.1, `AutoShardedClient`, the Server Members intent, `chunk_guilds_at_startup=False` and member cache flags from the intents.

| Check | Result |
|---|---|
| Shards and guilds at ready | 1 shard, 1 guild |
| Members reported against members cached | `member_count` 8, cached 1 (the bot), `chunked` false |
| `guild.query_members(query=..., limit=5)` | found the bot by name prefix over the gateway |
| `guild.fetch_member(...)` over REST | worked |
| Python heap at ready | 0.9 MB, peak 1.2 MB |

- With chunking off, a guild costs memory for the members the bot has seen, not for its member list (D25). Gateway member search works without a full list.
- The test server has 8 members, so memory for a large server is not measured here. It is checked when a large server is first available, and the plan's design does not depend on the number.

### Design changes from S4

None. D25 holds as written.
