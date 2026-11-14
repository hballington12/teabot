# Writing a teabot plugin

A plugin is a Python package that adds actions and jobs to teabot. Anyone running an instance can write one and install it without asking anyone (D44). This is the reference for `teabot.sdk` 1.x, which follows semantic versioning: breaking changes need a major version (D45). [tutorial.md](tutorial.md) builds a complete plugin step by step. Decision numbers such as (D21) point at [design.md](design.md).

## Starting a plugin

- In an instance set up by [self-hosting.md](self-hosting.md), `uv run teabot new-plugin raffles` writes `plugins/raffles/`: the package with its entry point, one example action, a first migration, a README, tests and a snapshot test.
- Start the Compose Postgres the tests use: `docker compose up -d --wait postgres`.
- Then `uv lock`, and run its tests with `uv run --env-file .env --package teabot-raffles pytest plugins/raffles`. The instance's `.env` holds the database password they use.
- Restart teabot, and turn the plugin on in a server with `/plugins enable plugin:raffles`.
- Worked examples: the first-party plugins, which ship inside teabot and import only `teabot.sdk` like yours, [giveaways](https://github.com/hballington12/teabot/tree/main/src/teabot/plugins/giveaways/__init__.py) (jobs, config, a plan) and [announcements](https://github.com/hballington12/teabot/tree/main/src/teabot/plugins/announcements/__init__.py) (posting now and later), in the teabot repository.

## The package

- A plugin imports only `teabot.sdk`, and its tests only `teabot.sdk` and `teabot.testing` (D45). Everything else in `teabot` is internal and may change in any release. `teabot check` and the test harness both refuse other imports.
- `pyproject.toml` declares an entry point in the `teabot.plugins` group, pointing at the plugin object. Its name must be the plugin's id:

    ```toml
    [project.entry-points."teabot.plugins"]
    raffles = "teabot_raffles:plugin"
    ```

- A plugin outside this repository depends on a compatible range of teabot, such as `teabot>=1.1,<2` (D14).
- Ship a `py.typed` marker, and a `README.md` with an "External connections" section listing every host the plugin contacts, or "none" (D12).

## The plugin object

```python
from teabot.sdk import Context, Plugin

plugin = Plugin("raffles", config=RafflesConfig)
type Ctx = Context[RafflesConfig]
```

- `Plugin(id, *, config=EmptyConfig, migrations=None)`. The version comes from the installed package, and migrations from `migrations/` beside the module that made the plugin, unless `migrations` names another directory.
- The id matches `[a-z][a-z0-9_]{1,31}`. `core`, `admin`, `teabot`, `plugin`, `plugins`, `audit` and `tokens` are reserved. Two installed packages with the same id both fail to load (D46).
- When the plugin loads, teabot imports every module of its package, so decorated functions in any module register themselves. It skips `tests`, modules whose names start with `_`, and `__main__`.
- Anything that fails while the plugin loads fails that plugin alone, which keeps none of its registrations. Everything else still loads (D14).
- To run code at load, subclass `Plugin` and override `setup(registrar)`, calling `super().setup(registrar)`.

## Actions

```python
@plugin.action(risk=WRITE, needs="manage_guild")
async def draw(ctx: Ctx, channel: TextChannel, prize: Annotated[str, Field(max_length=100)]) -> Drawn:
    """Draw a raffle winner.

    Args:
        channel: Where to announce the winner
        prize: What the winner gets
    """
```

- `@plugin.action(*, risk=WRITE, needs=(), name=None, reply="private")`.
- The function's name is the action's name, so this is the slash command `/raffles draw`, the MCP tool `raffles_draw` and the service action `raffles.draw` (D1). `name=` overrides it, and a trailing underscore is dropped, so `list_` is `list`.
- `risk` is `READ` (no side effects), `WRITE` (easy to undo) or `DESTRUCTIVE` (bulk or hard to undo). A destructive action needs a plan and always runs in two steps (D21).
- `needs` is a Discord permission, or a tuple of them, by discord.py's name, such as `"manage_messages"`. The core checks it live on every call (D18, D19), and pyright checks the names.
- `reply="public"` shows the reply to the channel. Replies are private by default.
- The docstring's first line is the summary. Its `Args:` section describes every input, each in at most 100 characters. A missing entry fails the load and names the line.

### Inputs

Every parameter after the context is an input. Each may be optional (`X | None = None`) or have a default.

| Type | In Discord |
|---|---|
| `str`, `int`, `bool` | a text, number or true/false option |
| `Literal["a", "b"]`, or a `Literal` of ints | a choice |
| `LongText` | multi-line text, typed in a modal |
| `TextChannel`, `Role`, `Member` | a picker; the function receives the channel, role or member itself |
| `ChannelRef`, `RoleRef`, `MemberRef` | a picker; the function receives the Discord ID |

- Limits go in `Annotated[int, Field(ge=1, le=20)]` or `Annotated[str, Field(max_length=100)]`. Discord enforces them before the member sends.
- A `TextChannel` that is missing or takes no messages, or a `Role` or `Member` not in the server, is refused with a message the member sees, and the function does not run.
- Any other type fails the load (D29).

### Outputs

- An action returns a Pydantic model, a list of models, or a `str`.
- In Discord a model is shown through its `render()` method if it has one, and otherwise as an embed of its fields. A list is shown one line per item, and a string as written.
- Mark text that members wrote as `UntrustedText`, which MCP clients receive wrapped as data (D23).
- To tell the member what went wrong, raise `ActionError("That raffle has ended.")`. The message is shown as written and recorded in the audit log. Any other exception shows a generic reply and keeps its details in the audit log.

### Plans

```python
@cancel.plan
async def plan_cancel(ctx: Ctx, raffle: int) -> Diff:
    entries = await ctx.db.fetch(Entry, ENTRIES, ctx.guild.id, raffle)
    return Diff(entries=[DiffEntry(change="remove", target=e.name, key=e.id) for e in entries])
```

- A destructive action's plan takes the same inputs and returns a `Diff` of what it would change. Without a plan the load fails.
- The member sees the plan and confirms it within 15 minutes. If what it shows has changed by then, they get a fresh plan, marked stale, instead (D21).
- The action then runs as a job and reads the confirmed plan as `ctx.diff`. An entry's `key` carries what the apply needs, such as a row id, so it changes exactly what the member saw.
- A destructive action returns a model, a list or a string like any other, but the member does not see it: they see the plan, then that the change is applying. Report what it did with `await ctx.report({...})`, which `/admin job_status` shows.

## The context

`ctx` is for one server (D2):

- `ctx.guild`: the server, as a `Guild`. `get_text_channel(id)`, `get_role(id)` and `await get_member(id)` find things in it, or return `None`.
- `ctx.actor`: who asked. `user_id` is the member, `via` how the call came in (`"slash"`, `"component"` for a button or a confirmation, `"mcp"`, `"service"`, or `"job"`), and `token_id` the token for MCP and service calls. In a job, it is the member who scheduled it, or `SYSTEM`.
- `ctx.config`: the plugin's config for this server, as the plugin's own model.
- `ctx.db`: the plugin's database, as its own role in its own schema.
- `ctx.now`: the time. Read the clock only through it, since tests move it.
- `ctx.diff`: in a destructive action's apply, the confirmed plan, and an empty `Diff` everywhere else.
- `await ctx.report(progress)`: progress for `/admin job_status`.

To post, send to a `TextChannel`:

```python
await channel.send("**A pet** goes to <@123>.", ping=[123])
await channel.send(embed=discord.Embed(title="Results"))
```

- Messages mention nobody unless you name members with `ping=`.
- A channel the bot may not post in raises an `ActionError` that says so.

## The database

- The plugin owns the schema `plugin_<id>` and a role that can use nothing else (D9). Name tables without a prefix. Reading the core or another plugin's tables fails.
- Every table has a `bigint guild_id` column, and the migration runner refuses tables without one. That is how the core deletes a server's data when the bot leaves it (D49).
- Every query must filter by `guild_id` itself (`WHERE guild_id = $1` with `ctx.guild.id`). A query without the filter sees every server's rows.
- A foreign key includes `guild_id`, so a row cannot point at another server's row. A unique index includes `guild_id` unless one of its columns is unique on its own. teabot checks these when the plugin loads, along with no views and no `SECURITY DEFINER` functions, and a broken rule stops the load with what to write instead.
- Queries take the result type first: `fetch(Model, sql, ...)` returns a list of models, `fetchrow(Model, sql, ...)` a model or `None`, and `fetchval(int, sql, ...)` one value. Each row is validated. `execute(sql, ...)` returns Postgres's status, such as `"INSERT 0 1"`.
- Each call runs exactly one statement. Pass values as parameters (`$1`, `$2`), never by building strings.
- Writes that belong together go in a transaction block, and everything inside it goes through `tx`:

    ```python
    async with ctx.db.transaction() as tx:
        raffle = await tx.fetchval(int, INSERT_RAFFLE, ctx.guild.id, prize, ends_at)
        await tx.schedule(announce_winner.bind(raffle=raffle), at=ends_at)
    ```

    - A job queued with `tx.schedule` commits together with the writes.
    - Calling `ctx.db` inside an open block raises, because it would miss the block's writes.
    - Never await Discord or HTTP inside a block. It holds a connection and its locks across a slow call.
- Use `now()` in SQL for the time, never `CURRENT_TIMESTAMP`, since tests move `now()`.
- Never build dynamic SQL from member input in a plpgsql function (`EXECUTE`). It is the one way an injection bug could reach another plugin's data.
- Never block the event loop. Use async libraries for any I/O (D33).

## Migrations

- `migrations/0001_<name>.sql`, `0002_<name>.sql` and so on, numbered from 1 with no gaps. Each runs once, in its own transaction, as the plugin's role (D9).
- Migrations only go forward. Never edit one that has been released, since the runner refuses a changed file.
- Keep the previous release working: add columns and tables in one release, and drop them in a later one (D15).

## Config

- A Pydantic model, passed as `Plugin(..., config=Model)`. Server admins set it with `/plugins config plugin:raffles setting:<name> value:<value>`. Without a setting, the command shows the current values. A value is read as JSON when it is JSON (numbers, `true`, `false`), and as the text typed otherwise, then validated through the model.
- Give every field a default, so a server that has set nothing still works.
- The plugin never writes to its config. Anything the plugin writes goes in its tables.
- Change it only in ways older stored config still validates: new fields with defaults, `AliasChoices` for renames, `extra="ignore"` for removals, `model_validator(mode="before")` for anything else (D10).
- Keep stored samples from earlier versions in `tests/fixtures/` and test that they still validate.

## Jobs

```python
@plugin.job
async def announce_winner(ctx: Ctx, raffle: int) -> None:
    ...
```

- A job's parameters after the context are its payload. It is stored as JSON, so give them types that survive the trip, such as `int`, `str`, `bool`, `Literal`s, and lists, optionals and models of them.
- `announce_winner.bind(raffle=3)` fixes the arguments, checked by pyright. `tx.schedule(bound, at=when)` queues it for this server, or as soon as possible without `at` (D31).
- A job's key is its name and arguments. Scheduling the same bound job again moves it instead of adding another, and `tx.unschedule(bound)` removes it. `key=` sets a key of your own instead.
- The job's name is the function's name, and queued jobs are stored by it. To rename the function, keep the stored name with `@plugin.job(name="old_name")`.
- In a job, `ctx.actor` is the member who scheduled it and `ctx.config` is the server's config when it runs. If the bot has left the server, the job is dropped.
- A job can run twice: after a crash, its lease runs out and another worker takes it. Check state first, so that a second run changes nothing, and test it with `harness.run_job`.
- A failing job is retried after 2, 4, 8 and 16 seconds, five attempts in all, then stays failed with its error, which `/admin job_status` shows. Raise `ActionError` to give that error in your words.

## Testing

- Install `teabot[testing]` and run Postgres 16: `docker compose up -d --wait postgres` starts the instance template's. Add `-p teabot.testing.fixtures` to pytest's `addopts`. If Postgres is not reachable, the run stops at once and says what to start.
- `teabot_harness` loads the plugin through the real loader and migrations into a fake server:

    ```python
    async def test_draw_announces_a_winner(teabot_harness: HarnessFactory) -> None:
        harness = await teabot_harness(plugin)
        channel = harness.guild.add_channel(FakeChannel())
        out = await harness.call(draw, channel=channel, prize="A pet")
    ```

- The harness runs `teabot check` on the plugin's package when it loads it, and raises `CheckFailed` with each problem.

| Helper | What it does |
|---|---|
| `harness.call(action, ...)` | runs an action through the real call path, permissions and audit included, as the server's first member, who has Administrator; returns what the function returned |
| `harness.as_member(member).call(...)` | the same, as another member; `.plan(...)` too |
| `harness.plan(action, ...)` | a destructive action's `Planned` |
| `harness.confirm(plan)` | confirms the plan and runs the apply |
| `harness.run_jobs()` | runs every due job through the real worker; a failure raises `JobFailed` with the job's exception as its cause |
| `harness.run_job(job.bind(...))` | runs a job now, as if scheduled again; after its own run, it tests that a second run changes nothing |
| `harness.advance(minutes=...)` | moves the clock for `ctx.now`, `now()` in the plugin's SQL, and when jobs fall due; the jobs then due run at the next `run_jobs` |
| `harness.configure(Cfg(...))` | stores the server's config, as an admin would |
| `harness.invoke(name, raw)` | calls by name with raw input, as a front door would; for testing refusals of bad input |
| `harness.admin` | a connection that can read every table, for checking what a test wrote |

- `harness.guild.add_channel(FakeChannel())` adds a channel, whose `sent` lists what was posted. `FakeChannel(forbidden=True)` refuses to send, and `FakeVoiceChannel` takes no messages.
- `harness.guild.add_member(permissions, roles=[...], cached=False)` adds a member, found only over REST when `cached=False`. `harness.guild.add_role(name)` adds a role.
- A column whose `DEFAULT now()` is filled in while the migration runs does not follow the test clock. Rows inserted later do.
- A refusal raises `Refused` with one of these codes, and an `ActionError` raises `ActionFailed`, whose `public_message` is what the member saw:

    | Code | Meaning |
    |---|---|
    | `forbidden` | the member lacks the action's Discord permissions |
    | `invalid_input` | the input does not fit the action's inputs |
    | `plugin_not_enabled` | the plugin is not enabled in this server |
    | `config_invalid` | the server's stored config no longer fits the plugin's model |
    | `not_in_guild` | the member is not in the server |
    | `unknown_action` | no action has that name |
    | `wrong_surface` | the action is not offered through this front door |
    | `above_token_risk`, `not_allowed_by_token` | a token's limits refuse the action |
    | `confirm_unknown`, `confirm_mismatch`, `plan_expired`, `plan_used` | a confirm value does not match a live plan of this member's |

### Snapshots

```python
def test_the_plugin_matches_its_snapshot(teabot_snapshot: SnapshotCheck) -> None:
    teabot_snapshot(plugin, Path(__file__).parent / "snapshot.json")
```

- The snapshot records what the plugin shows the world: its slash commands, its MCP tools and its jobs' payloads. The first run writes it.
- A change fails the test with the difference. When the change is meant, add `--teabot-accept` to the test command, such as `uv run --env-file .env --package teabot-raffles pytest plugins/raffles --teabot-accept`, and commit the new snapshot. A renamed input or job argument is then a decision, since it breaks queued jobs and the commands members know.
- Name the file `test_<id>_snapshot.py`, so that plugins in one instance never share a test module name.

## Review checklist

`uv run teabot check plugins/raffles` checks the first four, and the harness runs the same checks. The PR template repeats this list for first-party plugins.

- Imports only `teabot.sdk`, and tests only `teabot.sdk` and `teabot.testing`.
- Reads the time through `ctx.now` and `now()`, never `datetime.now()`, `time.time()` or `CURRENT_TIMESTAMP`.
- No `SET`, `RESET` or `set_config` in SQL.
- External connections listed in the README, and nothing else contacted.
- Every table has `guild_id`, every query filters by it, and released migrations are unchanged.
- No Discord or HTTP awaits inside transaction blocks, and no blocking I/O.
- No dynamic SQL built from member input.
- Jobs are safe to run twice.

## Lower level

`Plugin` builds an object with a `manifest` (`Manifest(id, version, config=, migrations=)`) and a `setup(registrar)` that registers `ActionSpec`s and job handlers. The loader accepts any object of that shape, described by the `LoadablePlugin` protocol, for plugins that build their actions at run time.
