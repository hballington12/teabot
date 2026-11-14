# Writing a teapot plugin

A plugin is a Python package that adds actions to teapot. Anyone running an instance can write one and install it without asking anyone (D44). This guide covers SDK 0.x; it becomes 1.0 at milestone 7, after which breaking changes need a major version (D45). Decision numbers point at the [README](../README.md).

## Starting a plugin

- In your instance, `uv run teapot new-plugin raffles` writes `plugins/raffles/`: the package with its entry point, a manifest with one example action, a first migration, a README and tests.
- Then `uv lock`, and run its tests against the Compose Postgres with `uv run --env-file .env --package teapot-raffles pytest plugins/raffles`.
- Restart teapot, and `/plugins enable raffles` in a server.

## The package

- A plugin imports only `teapot.sdk` (D45). Everything else in `teapot` is internal and may change in any release. First-party plugins have an import-linter contract checking this.
- `pyproject.toml` declares an entry point in the `teapot.plugins` group, pointing at the plugin object:

    ```toml
    [project.entry-points."teapot.plugins"]
    raffles = "teapot_raffles:plugin"
    ```

- A plugin outside this repository depends on a compatible range of teapot, such as `teapot>=1.2,<2` (D14).
- Ship a `py.typed` marker, and a `README.md` with an "External connections" section listing every host the plugin contacts, or "none" (D12).

## The plugin object

```python
from teapot.sdk import Manifest, Registrar


class Raffles:
    manifest = Manifest("raffles", "0.1.0", config=RafflesConfig, migrations=Path(__file__).parent / "migrations")

    def setup(self, registrar: Registrar) -> None:
        registrar.action(DRAW)
        registrar.job("announce_winner", announce_winner)


plugin = Raffles()
```

- The id matches `[a-z][a-z0-9_]{1,31}`. `core`, `admin`, `teapot`, `plugin`, `plugins`, `audit` and `tokens` are reserved. Two installed packages with the same id both fail to load (D46).
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

## What an action receives

`ctx` is for one server (D2):

- `ctx.guild`: the server. `ctx.actor`: who asked.
- `ctx.config`: the plugin's config for this server, validated through the plugin's config model.
- `ctx.db`: the plugin's database, as its own role in its own schema.
- `ctx.queue`: schedule the plugin's jobs for this server.

## The database

- The plugin owns the schema `plugin_<id>` and a role that can use nothing else (D9). Name tables without a prefix; reading the core or another plugin's tables fails.
- Every table has a `bigint guild_id` column; the migration runner refuses tables without one. That is how the core deletes a server's data when the bot leaves it (D49).
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

- A Pydantic model, set by server admins. The plugin never writes to its config; anything the plugin writes goes in its tables.
- Change it only in ways older stored config still validates: new fields with defaults, `AliasChoices` for renames, `extra="ignore"` for removals, `model_validator(mode="before")` for anything else (D10).
- Keep stored samples from earlier versions in `tests/fixtures/` and test that they still validate.

## Jobs

- `registrar.job(name, handler)` registers one; `tx.schedule` or `ctx.queue.schedule` queues it for a server (D31).
- A handler receives `guild_id`, `payload`, `db` (as in actions), `client` and `report(progress)`.
- A job can run twice: after a crash, its lease runs out and another worker takes it. Write handlers so a second run changes nothing.
- A failing job retries with growing delays, then stays failed with its error.

## Testing

- Install `teapot[testing]` and run Postgres 16 (the instance template's Compose file has one). Add `-p teapot.testing.fixtures` to pytest's `addopts`.
- `teapot_harness` loads the plugin through the real loader and migrations into a fake server, and `harness.invoke` runs actions through the real call path, permissions and audit included:

    ```python
    async def test_draw_picks_an_entrant(teapot_harness):
        harness = await teapot_harness(plugin)
        channel = harness.guild.add_channel(FakeChannel())
        out = await harness.invoke("raffles.draw", {"channel": str(channel.id), "prize": "A pet"})
    ```

- Tests import only `teapot.sdk` and `teapot.testing`, which also has what `invoke` raises and returns: `Refused` (check its `code`) before the action runs, `ActionFailed` (check its `public_message`) when the action raised, and a destructive action's `Planned` and `Queued`.
- `harness.guild.add_member(permissions, cached=False)` adds a member found only over REST. `FakeChannel(forbidden=True)` refuses to send; `FakeVoiceChannel` takes no messages.

## Review checklist

The PR template repeats this list for first-party plugins.

- Imports only `teapot.sdk`.
- External connections listed in the README, and nothing else contacted.
- Every table has `guild_id`; released migrations unchanged.
- No Discord or HTTP awaits inside transaction blocks, and no blocking I/O.
- No dynamic SQL built from member input.
- Jobs are safe to run twice.
