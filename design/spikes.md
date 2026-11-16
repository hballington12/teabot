# Spike findings

Findings from the spikes: short experiments that settled open technical questions before the code was written. The spike scripts were throwaway and live in the uncommitted `tmp/spikes/`, so this file is the record. Each section ends with what changed in the design.

## S1 asyncpg roles and protocol

Run on 2026-11-13 against Postgres 16.16 and asyncpg 0.30, with a core table, two plugin schemas and their roles.

### Pool reset

- asyncpg's pool runs `SELECT pg_advisory_unlock_all(); CLOSE ALL; UNLISTEN *; RESET ALL;` when a connection is released.
- `RESET ALL` resets `search_path`, and does **not** reset the role. A connection released after `SET ROLE teabot_plugin_x` came back from the next acquire still as `teabot_plugin_x`.
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

With the connection logged in as `teabot_app` and switched to `teabot_plugin_x`:

| Attempt | Result |
|---|---|
| Read `core.tokens` or another plugin's table directly | refused: permission denied for schema |
| Injected `UNION SELECT ... FROM core.tokens` | refused: permission denied for schema core |
| Injected stacked `; RESET ROLE; SELECT ... FROM core.tokens` through `fetch` | refused: multiple commands |
| The same through argument-less `execute` | **succeeded**, role back to `teabot_app` |
| Injected single expression `set_config('role', 'teabot_app', false)` through `fetch` | **succeeded**. The role changed for every later statement on the connection, and the next query read `core.tokens`. `set_config('role', 'teabot_plugin_y')` reached the other plugin's data the same way |
| `set_config` and a read of `core` in the same statement | refused. The new role only applies from the next statement |

The design's claim that one statement per call makes the role a hard limit for SQL injection (D9) was therefore false. A single injected expression escapes.

### Closing the escape

- Revoking `EXECUTE` on `pg_catalog.set_config(text, text, boolean)` from `PUBLIC`, and granting it back to `teabot_app`, refused the injected `set_config` with "permission denied for function set_config". Plugin reads, writes and `RETURNING` kept working, and `teabot_app` could still call `set_config`.
- One route remained. A plpgsql function in the plugin's own schema that runs dynamic SQL (`EXECUTE sql`) could still run `SET ROLE teabot_app`, because `SET ROLE` is checked against the session user, and the session user was `teabot_app`.
- With the plugin connection logged in as a separate session user `teabot_plugins`, which has no rights of its own and is only a member of the plugin roles, the same function was refused `SET ROLE teabot_app`. It could still switch to another plugin's role that `teabot_plugins` is a member of.

### Queuing jobs from a plugin role

- Inside a `SECURITY DEFINER` function, `current_user` is the function's owner, so the planned `core.schedule_job` could not tell which plugin called it.
- A function `plugin_x.schedule_job(guild_id, handler)` owned by `teabot_app`, `SECURITY DEFINER`, with `SET search_path = core, pg_temp` and the plugin id written into its body, worked:
    - plugin `x` queued a job through it, and the row carried the plugin id `x`
    - plugin `x` still could not read `core.jobs`
    - plugin `x` could not replace the function, because it does not own it

### Design changes from S1

- **Two session users (D9, D30).** The core's pool logs in as `teabot_app`. Plugin code uses a second pool that logs in as `teabot_plugins`, which has no rights of its own and is a member of every plugin role. A plugin connection runs `SET ROLE` and sets `search_path` on acquire, and `RESET ROLE` on release.
- **`set_config` is revoked from `PUBLIC`** and granted to `teabot_app` and the owner. `teabot init` does this. It needs a superuser once. On managed Postgres without a superuser, `teabot init` warns, and the injection limit falls back to review.
- **Helpers use prepared statements only.**
- **What the role now guarantees.** An SQL injection bug in a plugin cannot reach `core`, where token hashes live, and cannot change the role through `set_config`. Reaching another plugin needs a plpgsql function in that plugin which runs dynamic SQL built from untrusted input. The authoring guide forbids that, and review checks it.
- **Per-plugin `schedule_job`.** The migration runner creates `plugin_<id>.schedule_job` for each plugin, owned by `teabot_app`, with the plugin id built in, and grants `EXECUTE` only to that plugin's role. `core.schedule_job` is dropped from the design.

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
| `LISTEN teabot_jobs` on the lock-holding connection, with `pg_notify` from another connection, inside and outside a transaction | both notifications arrived, and the lock stayed held |

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
- A bot cannot invoke its own slash commands, so receiving a live interaction was confirmed by a person running the command in the test server.

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

## S5 MCP low-level server

Run on 2026-11-13 with `mcp` 2.3.0 in process, through `httpx.ASGITransport` (`tmp/spikes/mcp/s5_server.py`).

| Check | Result |
|---|---|
| A low-level `Server` with `on_list_tools` and `on_call_tool` as constructor arguments | worked; 2.x has no handler decorators, and a handler is `async (ctx, params)` |
| `BearerAuthBackend` with a `TokenVerifier`, `RequireAuthMiddleware`, no OAuth server | no token and an unknown token both get 401 `invalid_token` |
| `tools/list` with a read token, then a write token | one tool, then two: the handler reads the token from `ctx.request.user` on every call, and nothing caches the list |
| `tools/list` in stateless mode with no `initialize` first | worked |
| `instructions` on the `Server` | returned in the `initialize` result |
| `ToolAnnotations(read_only_hint=..., destructive_hint=...)` | sent as `readOnlyHint` and `destructiveHint` |
| A tool result with `is_error=True` | returned as a result with `isError: true` and its text |
| `TransportSecuritySettings` with the public host, request with that `Host` | 200 |
| The same, with `Host` rewritten to the upstream address | 421 `Invalid Host header` |
| A foreign `Origin`, then the public one | 403, then 200 |

- The SDK checks the raw `Host` header and reads no `X-Forwarded-*` header. The reverse proxy must pass the original `Host` through. Caddy does by default, and nginx needs `proxy_set_header Host $host`.
- Without `security_settings` the manager turns DNS-rebinding protection off. teabot always passes settings with the public hostname.
- A raised exception becomes a JSON-RPC error, not an `isError` result. That differs from 1.x. A refusal or a failed action must be returned as `isError`, so the LLM sees the reason.
- Stateless mode answers each request on its own transport, with no session to bind to a token or to a process. Any process can serve any MCP request (D40).
- On the 2026-07-28 protocol, header validation may call the `tools/list` handler itself. Passing `get_tool_input_schema=` avoids that, and the schema builder already has each tool's schema.
- The tool list's `ttlMs` cache hint defaults to 0 with scope `private`, so clients are not told to reuse one token's list for another.

### Design changes from S5

- A `WRITE` tool sends `destructiveHint: false` explicitly, because the spec treats a tool without the hint as destructive (D22).
- The adapter runs in stateless mode with JSON responses, and returns refusals and action errors as `isError` results.
- The reverse proxy must keep the original `Host` header. The instance template's proxy config says so.

## S6 row-level security for plugin tables

Run on 2026-11-14 with Postgres 16, before building server scoping (D9, D47). It mirrors production: a non-superuser instance owner, a login role for the plugin pool, and for each plugin an owner role, which owns the schema and runs migrations, and a runtime role, which plugin code uses. Each table gets a policy for the runtime role, `guild_id = nullif(current_setting('teabot.guild_id', true), '')::bigint`, and the same expression as `guild_id`'s default. The core sets `teabot.guild_id` with `SET ROLE` when it hands out a connection, and resets both on release. All 28 checks passed.

- **Scoping works.** A scoped read sees only its server's rows, an insert without `guild_id` fills it from the scope, and an insert or update naming another server is refused by the policy.
- **The `nullif` is needed.** After a reset, a pooled connection reads the setting back as `''`, not NULL, and `''::bigint` raises. With `nullif`, an unscoped read returns no rows on fresh and reused connections alike.
- **An unscoped insert is refused by the policy, not by `NOT NULL`.** Postgres checks the policy first, so the error names row-level security rather than `guild_id`.
- **The owner role is exempt,** since the tables are not set to `FORCE`, so migrations see every server's rows. The runtime role cannot turn the policy off or create tables.
- **Plugin code can widen its own scope with a plain `SET`,** since any role may set a custom setting. An injected fragment inside one statement cannot, because `set_config` is revoked. Accepted: plugins are chosen by the operator and public ones vetted (D44), and a lint flags `SET` in plugin SQL.
- **Constraints the policy does not cover:**
    - A single-column foreign key accepts another server's id, revealing that the row exists. A row in one server referencing another server's row also blocks that server's purge (D49).
    - A unique index without `guild_id` collides across servers, and its error tells one server what another holds.
    - A composite foreign key, `(guild_id, giveaway_id) REFERENCES giveaways (guild_id, id)`, refuses another server's parent.
- **Objects that get round the policy:** a plain view (it runs with its owner's rights), a materialized view (it has no row-level security), and a `SECURITY DEFINER` function owned by the plugin each returned every server's rows. A view created `WITH (security_invoker = true)` stayed scoped.
- **Catalog queries find exactly these.** One query flags foreign keys without `guild_id`; one flags unique indexes holding neither `guild_id` nor an identity column; one flags plain views, materialized views and `SECURITY DEFINER` functions. The last must exempt functions the instance owner owns, such as `schedule_job`, which is `SECURITY DEFINER` by design.
- **`schedule_job` can read the server from the scope** inside its `SECURITY DEFINER` body, so it needs no server argument.
- **A purge scoped to a server** deletes that server's rows and no others.
- **The cost is small.** With 50,000 rows over 500 servers, the policy's filter used the `guild_id` index.

### Design changes from S6

- The pool never hands out an unscoped plugin connection, so the policy's refusal of an unscoped insert is a backstop, not a message an author meets.
- The load-time check for bypassing objects exempts functions owned by the instance owner.
- Foreign keys without `guild_id` are refused for two reasons, the existence leak and blocked purges.
- The spike script is `tmp/spikes/s6_rls.py`.

## S7 the decorator API's types

Run on 2026-11-14 with pyright in strict mode on Python 3.12, before building the 1.1 authoring API. A typed prototype of the API (`Plugin`, `@plugin.action`, `@plugin.job`, `bind`, `Context`, `harness.call`) carried a port of the authoring trial's giveaways plugin and its tests. The prototype is `tmp/spikes/s7/`.

- **Inference works end to end.** `Plugin("giveaways", config=Cfg)` is inferred as `Plugin[Cfg]`. A decorated action keeps its signature without the context, as `Action[Cfg, (channel: int, prize: str, winners: int = 1, minutes: int | None = None), Started]`. `harness.call(start, channel=1, prize="x")` is typed as `Started`, and a list action as `list[Running]`. A job's `bind` is typed by the job's own parameters.
- **Pyright catches every mistake tried:** a wrong argument type, a missing argument and an unknown one, in both `harness.call` and `bind`; a misspelled permission in `needs=`; and an action whose context names the wrong config. That last message is long and generic, so the load error should say it plainly too.
- **A default config type needs the older form on 3.12.** `class Plugin[C: BaseModel = EmptyConfig]` is PEP 696 syntax, which pyright refuses below Python 3.13. `class Plugin(Generic[Cfg])` with `typing_extensions.TypeVar("Cfg", default=EmptyConfig)` works.
- **The input model builds from the signature at runtime.** Required and optional fields follow the defaults, the `Args:` section supplies each description, a parameter annotated with the `type Ctx = Context[Cfg]` alias is recognised as injected once the alias's `__value__` is followed, and an action with no parameters gets an empty model.
- **The docstring rules work at load.** A parameter with no `Args:` entry, an `Args:` entry naming no parameter, and a description over 100 characters each fail with the action's name.
- **One silent loss found.** `get_type_hints` strips `Annotated` metadata unless called with `include_extras=True`, so `Annotated[int, Field(ge=1, le=20)]` lost its limits without a word. With it, `minimum` and `maximum` reach the schema. The real build needs a test for this.

### Design changes from S7

- `Plugin` is declared with `Generic` and a `typing_extensions.TypeVar` default while teabot supports 3.12.
- Signatures are read with `get_type_hints(..., include_extras=True)`, tested with a limit on an `Annotated` parameter.
- A context with the wrong config also fails at load with a plain message, since pyright's is hard to read.

## S8 voice and music from PyPI packages

Run on 2026-11-15 on Windows 11 with Python 3.13, before designing voice (D6, D54). The question was whether a music plugin can play YouTube, Spotify and SoundCloud links in a voice channel using only packages from PyPI, with no separate audio server such as Lavalink. A plain discord.py client stood in for teabot, with discord.py 2.7.1 and its `voice` extra (PyNaCl, davey), PyAV 19.0.2, whose wheels bundle FFmpeg and libopus, yt-dlp 2026.10.26 with yt-dlp-ejs 0.8.0, and Deno 2.9.8, also installed from PyPI, which yt-dlp needs to solve YouTube's JavaScript challenges. Each package came in through `uv run --with`, so teabot's lock file was untouched. The script is `tmp/spikes/s8/music_spike.py`.

| Check | Result |
|---|---|
| Resolve 18 sources and read their first 5 s of audio: 11 YouTube links (one on music.youtube.com, one inside a playlist), 3 Spotify tracks, 1 SoundCloud track, 2 searches | 17 played. One YouTube link was refused with 403 on its first try only |
| Read a YouTube stream URL as soon as yt-dlp returns it | 403 every time, until the format's `available_at`, 5 to 6 s later; then it reads directly, with no Range requests needed |
| What YouTube serves | Opus at 48 kHz in 20 ms packets, which Discord takes as they are |
| A Spotify track | its page's `og:title` and `og:description` give the title and artist, with no API key; a YouTube search on them found the official video for all 3 |
| Join a voice channel | 0.5 to 0.9 s; DAVE protocol 1 negotiated |
| Play with davey 0.2.0, nobody listening, then with a member in the channel | plays without error, but with a member present the session never becomes ready: `can_encrypt` stayed false for 60 s, discord.py sent the audio unencrypted, and the member heard nothing while the bot showed as speaking |
| The same with davey 0.1.7 | ready within 5 s, `can_encrypt` true at every check for 3 minutes; the member heard it clearly |
| Time from request to first audio | YouTube 7.5 to 9 s, nearly all of it the `available_at` wait; SoundCloud 2.3 s |
| Cost of one stream, 16-core machine | YouTube copied without re-encoding: 0.4 to 1% of one core. Re-encoded by PyAV's libopus (SoundCloud's AAC, or YouTube forced): about 2%. Memory 107 MB for the whole process, 15 MB above idle |
| Kill the process mid-track without disconnecting, then start again | Discord still showed the bot in the channel; the new process joined in 0.5 s and played |
| A whole track | 198 s played to the end, encrypted throughout, and the bot left |

- **discord.py 2.7.1 and davey 0.2 do not work together.** davey 0.2 needs `prepare_transition` and `execute_transition` after a commit or welcome before it uses the new keys. discord.py 2.7.1 never calls them, since it was written against davey 0.1, and it requires only `davey>=0.1.0`. Any bot installing `discord.py[voice]` today gets silence for every listener. Nothing fails, so a test without a listener does not catch it.
- **The YouTube wait is per track.** Joining while resolving hides the join, but not the wait. Resolving the next track while the current one plays hides it for every track after the first.
- **PyAV covers decoding and encoding.** Its wheels carry FFmpeg and libopus, so neither an FFmpeg binary nor a system Opus library is needed, on Windows or, by its wheels, on Linux. Re-encoding needs each decoded frame's `pts` cleared before the resampler, which refuses the gaps Opus pre-skip leaves.
- **Playback runs off the event loop.** discord.py's player reads each packet on its own thread, and yt-dlp blocks for a few seconds, so neither touches the loop (D33) as long as resolving runs in a thread.
- **Not checked:** Linux, ARM wheels for PyAV and davey, several servers playing at once, seeking to resume mid-track, and how long a resolved stream URL stays valid.

### Design changes from S8

- Voice needs no separate audio server. D54 builds it on discord.py's voice client, with PyPI packages only.
- teabot's `voice` extra pins `davey<0.2` until discord.py supports davey 0.2.
- Sources are the music plugin's dependencies, not the core's: the core plays Opus packets, and the plugin finds them.
- A music plugin resolves the next track while one plays, and keeps resolving off the event loop.
