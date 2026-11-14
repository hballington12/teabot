# Writing a teabot plugin

A plugin is a Python package that adds actions to teabot. Anyone running an instance can write one and install it without asking anyone (D44). It covers `teabot.sdk` 1.x, which follows semantic versioning: breaking changes need a major version (D45). Decision numbers point at [design.md](design.md).

## Starting a plugin

- In your instance, `uv run teabot new-plugin raffles` writes `plugins/raffles/`: the package with its entry point, a manifest with one example action, a first migration, a README and tests.
- Start the Compose Postgres the tests use: `docker compose up -d --wait postgres`.
- Then `uv lock`, and run its tests with `uv run --env-file .env --package teabot-raffles pytest plugins/raffles`.
- Restart teabot, and turn the plugin on in a server with `/plugins enable plugin:raffles`.
- For a complete worked example, read the first-party announcements plugin, [`plugins/announcements/src/teabot_announcements/__init__.py`](../plugins/announcements/src/teabot_announcements/__init__.py): it posts to a channel, schedules a job, and handles a channel the bot cannot post in.

## The package

- A plugin imports only `teabot.sdk` (D45). Everything else in `teabot` is internal and may change in any release. First-party plugins have an import-linter contract checking this.
- `pyproject.toml` declares an entry point in the `teabot.plugins` group, pointing at the plugin object:

    ```toml
    [project.entry-points."teabot.plugins"]
    raffles = "teabot_raffles:plugin"
    ```

- A plugin outside this repository depends on a compatible range of teabot, such as `teabot>=1.2,<2` (D14).
- Ship a `py.typed` marker, and a `README.md` with an "External connections" section listing every host the plugin contacts, or "none" (D12).

## The plugin object

```python
from teabot.sdk import Manifest, Registrar


class Raffles:
    manifest = Manifest("raffles", "0.1.0", config=RafflesConfig, migrations=Path(__file__).parent / "migrations")

    def setup(self, registrar: Registrar) -> None:
        registrar.action(DRAW)
        registrar.job("announce_winner", announce_winner)


plugin = Raffles()
```

- The id matches `[a-z][a-z0-9_]{1,31}`. `core`, `admin`, `teabot`, `plugin`, `plugins`, `audit` and `tokens` are reserved. Two installed packages with the same id both fail to load (D46).
- `setup` only registers. Anything it raises fails the plugin, which keeps none of its registrations; everything else still loads (D14).

## Actions

```python
class Draw(BaseModel):
    channel: ChannelRef = Field(description="Where to announce the winner")
    prize: str = Field(max_length=100, description="What the winner gets")


class Drawn(BaseModel):
    winner: int


DRAW = ActionSpec(
    "raffles.draw",
    "Draw a raffle winner",
    Draw,
    Drawn,
    Risk.WRITE,
    draw,
    default_permissions=discord.Permissions(manage_guild=True),
)
```

- The name is `<plugin id>.<action>`. An action becomes the slash command `/raffles draw`, the MCP tool `raffles_draw` and the service action `raffles.draw`, unless `surfaces` narrows it (D1).
- Risk is `READ` (no side effects), `WRITE` (easy to undo) or `DESTRUCTIVE` (bulk or hard to undo; it needs a `plan` and always runs in two steps, D21).
- `default_permissions` is what a member needs in Discord. The core checks it live on every call (D18, D19).
- Input fields may only be `str`, `LongText`, `int`, `bool`, a `Literal` of only strings or only ints, and `ChannelRef`, `RoleRef` or `MemberRef`, each optional or not (D29). Anything else is refused when the `ActionSpec` is built.
    - `LongText` is multi-line text; in Discord it is typed in a modal.
    - The ref types hold a Discord ID. Give fields a `description`; Discord shows it.
- Output is a model. In Discord it is shown through `render` if the action has one, or as an embed of its fields. Mark member-written text in outputs as `UntrustedText`, which MCP wraps (D23).
- To tell the member what went wrong, raise `ActionError("That channel is not a text channel.")`. The message is shown as written and recorded in the audit log. Any other exception shows a generic reply and keeps its details in the audit log.
- A destructive action's own output is not shown yet: the member sees the plan, then that the change is applying. Report what it did through `ctx.report(...)` progress, which `/admin job_status` shows.

## What an action receives

`ctx` is for one server (D2):

- `ctx.guild`: the server. `ctx.actor`: who asked.
- `ctx.config`: the plugin's config for this server, validated through the plugin's config model.
- `ctx.db`: the plugin's database, as its own role in its own schema.
- `ctx.queue`: schedule the plugin's jobs for this server.

To post somewhere, find the channel and send to it; this is how the announcements plugin does it:

```python
channel = cast(Any, ctx.guild.get_channel(data.channel))
if channel is None or not hasattr(channel, "send"):
    raise ActionError("That channel is not a text channel in this server.")
try:
    message = await channel.send(embed=discord.Embed(title=data.title, description=data.body))
except discord.Forbidden:
    raise ActionError("I am not allowed to post in that channel.") from None
```

In tests the server is a `FakeGuild`, whose channels are fakes, so code like this works in both. The `cast` is there because pyright cannot see that the fakes and discord.py's channels share `send`; the SDK's own Discord types will remove it.

## The database

- The plugin owns the schema `plugin_<id>` and a role that can use nothing else (D9). Name tables without a prefix; reading the core or another plugin's tables fails.
- Every table has a `bigint guild_id` column; the migration runner refuses tables without one. That is how the core deletes a server's data when the bot leaves it (D49).
- Nothing filters rows for you: every query must filter by `guild_id` itself (`WHERE guild_id = $1` with `ctx.guild.id`). A query without the filter sees every server's rows.
- Each helper call runs exactly one statement. Pass values as parameters (`$1`, `$2`), never by building strings.
- Writes go in a transaction block, and everything inside it goes through `tx`:

    ```python
    async with ctx.db.transaction() as tx:
        await tx.execute("INSERT INTO entries (guild_id, user_id) VALUES ($1, $2)", ctx.guild.id, user_id)
        await tx.schedule("announce_winner", run_at=ends_at, payload={"raffle": raffle_id})
    ```

    - A job queued with `tx.schedule` commits together with the writes.
    - Calling `ctx.db` inside an open block raises, because it would miss the block's writes.
    - Never await Discord or HTTP inside a block; it holds a connection and its locks across a slow call. Dev mode logs blocks held longer than 100 ms.
- Never build dynamic SQL from member input in a plpgsql function (`EXECUTE`). It is the one way an injection bug could reach another plugin's data.
- Never block the event loop. Use async libraries for any I/O (D33).

## Migrations

- `migrations/0001_<name>.sql`, `0002_<name>.sql` and so on, numbered from 1 with no gaps. Each runs once, in its own transaction, as the plugin's role (D9).
- Migrations only go forward. Never edit one that has been released; the runner refuses a changed file.
- Keep the previous release working: add columns and tables in one release, drop them in a later one. This becomes required when instances run several processes (D15).

## Config

- A Pydantic model, set by server admins with `/plugins config plugin:raffles setting:<name> value:<value>`. Without a setting, the command shows the current values. A value is read as JSON when it is JSON (numbers, `true`, `false`), and as the text typed otherwise, then validated through the model.
- `ctx.config` is typed as `BaseModel`; read your own model with `cast(RafflesConfig, ctx.config)` until the SDK types it.
- The plugin never writes to its config; anything the plugin writes goes in its tables.
- Change it only in ways older stored config still validates: new fields with defaults, `AliasChoices` for renames, `extra="ignore"` for removals, `model_validator(mode="before")` for anything else (D10).
- Keep stored samples from earlier versions in `tests/fixtures/` and test that they still validate.

## Jobs

- `registrar.job(name, handler)` registers one; `tx.schedule` or `ctx.queue.schedule` queues it for a server (D31).
- A handler receives one `JobContext`, with `guild_id`, `payload`, `db` (as in actions), `client` and `report(progress)`. To post from a job, find the channel with `ctx.client.get_channel(channel_id)`.
- A job can run twice: after a crash, its lease runs out and another worker takes it. Write handlers so a second run changes nothing.
- A failing job, including one that raises `ActionError`, is retried after 2, 4, 8 and 16 seconds, five attempts in all, then stays failed with its error, which `/admin job_status` shows.
- Known gap: `tx.schedule` and `ctx.queue.schedule` go through the plugin's `schedule_job` function, which takes the server's id as an argument, so plugin code could queue a job for another server. Always schedule for `ctx.guild.id`; a later release takes the server from the connection instead.

## Testing

- Install `teabot[testing]` and run Postgres 16: `docker compose up -d --wait postgres` starts the instance template's. Add `-p teabot.testing.fixtures` to pytest's `addopts`. If Postgres is not reachable, the run stops at once and says what to start.
- `teabot_harness` loads the plugin through the real loader and migrations into a fake server, and `harness.invoke` runs actions through the real call path, permissions and audit included:

    ```python
    async def test_draw_picks_an_entrant(teabot_harness):
        harness = await teabot_harness(plugin)
        channel = harness.guild.add_channel(FakeChannel())
        out = await harness.invoke("raffles.draw", {"channel": str(channel.id), "prize": "A pet"})
    ```

- Tests import only `teabot.sdk` and `teabot.testing`, which also has what `invoke` raises and returns: `Refused` (check its `code`) before the action runs, `ActionFailed` (check its `public_message`) when the action raised, and a destructive action's `Planned` and `Queued`.
- `harness.guild.add_member(permissions, cached=False)` adds a member found only over REST. `FakeChannel(forbidden=True)` refuses to send; `FakeVoiceChannel` takes no messages.
- Set config as an admin would: `await harness.invoke("plugins.config", {"plugin": "raffles", "setting": "max_entries", "value": "50"})`.
- Confirm a destructive action's plan by calling it again with the plan's confirm value, then run the apply:

    ```python
    plan = await harness.invoke("raffles.cancel", {"raffle": "3"})
    assert isinstance(plan, Planned)
    queued = await harness.invoke("raffles.cancel", {"raffle": "3", "confirm": plan.confirm})
    await harness.run_jobs()
    ```

- `harness.run_jobs()` runs every due job through the real worker. If a job fails, it raises `JobFailed` with the job's own exception as its cause, so the traceback shows; a test that expects a failure catches `JobFailed`. Until the SDK has a test clock, make a scheduled job due with `await harness.admin.execute("UPDATE core.jobs SET run_at = now() WHERE id = $1", job_id)`.
- A refusal raises `Refused` with one of these codes:

    | Code | Meaning |
    |---|---|
    | `forbidden` | the member lacks the action's Discord permissions |
    | `invalid_input` | the input does not fit the action's model |
    | `plugin_not_enabled` | the plugin is not enabled in this server |
    | `config_invalid` | the server's stored config no longer fits the plugin's model |
    | `not_in_guild` | the member is not in the server |
    | `unknown_action` | no action has that name |
    | `wrong_surface` | the action is not offered through this front door |
    | `above_token_risk`, `not_allowed_by_token` | a token's limits refuse the action |
    | `confirm_unknown`, `confirm_mismatch`, `plan_expired`, `plan_used` | a confirm value does not match a live plan of this member's |

## Review checklist

The PR template repeats this list for first-party plugins.

- Imports only `teabot.sdk`.
- External connections listed in the README, and nothing else contacted.
- Every table has `guild_id`; released migrations unchanged.
- No Discord or HTTP awaits inside transaction blocks, and no blocking I/O.
- No dynamic SQL built from member input.
- Jobs are safe to run twice.
