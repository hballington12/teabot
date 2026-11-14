# Tutorial: a giveaways plugin

This builds the first-party giveaways plugin step by step. Moderators start a giveaway in a channel, members enter, and a job draws the winners when time is up. The finished plugin is [`plugins/giveaways`](../plugins/giveaways), and its tests run with the rest of teabot's, so every line here is checked. [plugin-authoring.md](plugin-authoring.md) is the reference for each piece. Decision numbers such as (D21) point at [design.md](design.md).

## 1. Start the plugin

In your instance (see [self-hosting.md](self-hosting.md)):

```
docker compose up -d --wait postgres
uv run teabot new-plugin giveaways
uv lock
uv run --env-file .env --package teabot-giveaways pytest plugins/giveaways
```

`new-plugin` writes one package:

```text
plugins/giveaways/
    pyproject.toml                       the entry point, and a teabot version range
    README.md                            what it does, and its "External connections"
    src/teabot_giveaways/
        __init__.py                      the plugin: config, actions and jobs
        migrations/0001_greetings.sql
    tests/
        test_giveaways.py
        test_giveaways_snapshot.py       the commands, MCP tools and job payloads, as a snapshot
```

The example action is called `hello`. Replace it, and rename the migration to `0001_giveaways.sql`. A plugin is one file until it grows. Section 10 covers splitting it.

## 2. The plugin object and its config

```python
from pydantic import BaseModel, Field

from teabot.sdk import Context, Plugin, RoleRef


class Cfg(BaseModel):
    default_minutes: int = Field(default=60, ge=1, le=10080)
    excluded_role: RoleRef | None = None


plugin = Plugin("giveaways", config=Cfg)
type Ctx = Context[Cfg]
```

- `Plugin` reads its version from the installed package and finds `migrations/` beside the module. Its id must match the entry point's name in `pyproject.toml`. A mismatch fails the load and says which to change.
- `ctx.config` is a `Cfg`. Server admins set it with `/plugins config plugin:giveaways setting:default_minutes value:90`.
- `type Ctx = Context[Cfg]` names the config type once. Pyright then checks that every action and job takes the right context.

## 3. Tables

```sql
CREATE TABLE giveaways (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    guild_id bigint NOT NULL,
    channel_id bigint NOT NULL,
    prize text NOT NULL,
    winners int NOT NULL,
    ends_at timestamptz NOT NULL,
    state text NOT NULL DEFAULT 'running' CHECK (state IN ('running', 'drawn', 'cancelled')),
    UNIQUE (guild_id, id)
);

CREATE TABLE entries (
    guild_id bigint NOT NULL,
    giveaway_id bigint NOT NULL,
    member_id bigint NOT NULL,
    won boolean NOT NULL DEFAULT false,
    PRIMARY KEY (guild_id, giveaway_id, member_id),
    FOREIGN KEY (guild_id, giveaway_id) REFERENCES giveaways (guild_id, id)
);
```

- Every table has `guild_id`, and every query filters by it (D2).
- A foreign key includes `guild_id`, so a row can never point at another server's row. A unique index includes `guild_id` too, unless it holds a column that is unique on its own, such as the identity `id`.
- teabot checks these rules against the database when the plugin loads. A table that breaks one stops the load, with the constraint to write instead.

## 4. The first action

```python
class Started(BaseModel):
    giveaway: int
    ends_at: datetime

    def render(self) -> str:
        return f"Giveaway {self.giveaway} started; it ends <t:{int(self.ends_at.timestamp())}:R>."


@plugin.action(needs="manage_messages")
async def start(
    ctx: Ctx,
    channel: TextChannel,
    prize: Annotated[str, Field(max_length=200)],
    winners: Annotated[int, Field(ge=1, le=20)] = 1,
    minutes: Annotated[int, Field(ge=1, le=10080)] | None = None,
) -> Started:
    """Start a giveaway.

    Args:
        channel: Where to announce it.
        prize: What the winners get.
        winners: How many winners to draw.
        minutes: How long it runs; the server's default if left out.
    """
    ends_at = ctx.now + timedelta(minutes=minutes or ctx.config.default_minutes)
    async with ctx.db.transaction() as tx:
        giveaway = await tx.fetchval(int, START, ctx.guild.id, channel.id, prize, winners, ends_at)
        await tx.schedule(draw.bind(giveaway=giveaway), at=ends_at)
    await channel.send(announcement(prize, giveaway, ends_at))
    return Started(giveaway=giveaway, ends_at=ends_at)
```

- This one function is the slash command `/giveaways start`, the MCP tool `giveaways_start` and the service action `giveaways.start` (D1).
- The inputs are the parameters. The docstring's first line is the summary, and its `Args:` section describes each option everywhere. Every parameter needs an entry that fits Discord's 100 characters. A missing or long one fails the load and names the line.
- `channel: TextChannel` arrives as the channel itself, checked to exist and to take messages. Discord shows a channel picker for it.
- `Annotated[int, Field(ge=1, le=20)]` sets limits that Discord enforces before the member sends.
- `needs="manage_messages"` is checked live on every call (D18). Pyright catches a misspelled permission.
- `risk` defaults to `WRITE`, for changes that are easy to undo.
- `ctx.now` is the time. Tests can move it.
- `render` is the reply the member sees. Without one, Discord shows the output's fields.
- The draw is queued in the same transaction as the giveaway, so neither exists without the other. The announcement is sent after the commit, since nothing that waits on Discord belongs inside a transaction.

## 5. Queries

```python
class Running(BaseModel):
    id: int
    prize: UntrustedText
    ends_at: datetime
    entrants: int


@plugin.action(risk=READ, reply="public")
async def list_(ctx: Ctx) -> list[Running]:
    """The running giveaways."""
    return await ctx.db.fetch(Running, RUNNING, ctx.guild.id)
```

- `ctx.db.fetch(Running, ...)` returns `list[Running]`, each row validated. `fetchval(int, ...)` returns an `int`, and `fetchrow(Model, ...)` a model or `None`.
- The trailing underscore keeps the name `list`, which would otherwise shadow Python's.
- `reply="public"` shows the reply to the whole channel. Replies are private by default.
- A list of models is shown one line per item.
- `UntrustedText` marks text a member wrote, which MCP clients receive wrapped as data (D23).

## 6. Entering

```python
@plugin.action()
async def enter(ctx: Ctx, giveaway: int) -> str:
    """Enter a running giveaway.

    Args:
        giveaway: The giveaway's number, from /giveaways list.
    """
    excluded = ctx.config.excluded_role
    if excluded is not None:
        member = await ctx.guild.get_member(ctx.actor.user_id)
        if member is not None and excluded in member.role_ids:
            raise ActionError("Your role cannot enter giveaways here.")
    added = await ctx.db.execute(ENTER, ctx.guild.id, giveaway, ctx.actor.user_id)
    if added == "INSERT 0 1":
        return "You're in. Good luck!"
    raise ActionError("You are already in, or that giveaway is not running.")
```

- A plain string is a reply.
- `ctx.actor` says who called and through which front door. `ctx.guild.get_member(...)` finds them with their roles.
- `ActionError` tells the member what went wrong in your words, and the audit log records it. Any other exception shows a generic reply and keeps its details in the audit log.
- The `ENTER` query checks `ends_at > now()`. In tests, `now()` follows the test clock.

## 7. The draw: a job

```python
@plugin.job
async def draw(ctx: Ctx, giveaway: int) -> None:
    async with ctx.db.transaction() as tx:
        row = await tx.fetchrow(Drawable, LOCK_RUNNING, ctx.guild.id, giveaway)
        if row is None:
            return
        winners = await tx.fetch(int, PICK, ctx.guild.id, giveaway, row.winners)
        await tx.execute(MARK_WON, ctx.guild.id, giveaway, winners)
        await tx.execute(SET_STATE, ctx.guild.id, giveaway, "drawn")
    channel = ctx.guild.get_text_channel(row.channel_id)
    if channel is None:
        return
    if not winners:
        await channel.send(f"Nobody entered the giveaway for **{row.prize}**.")
        return
    named = ", ".join(f"<@{w}>" for w in winners)
    await channel.send(f"**{row.prize}** goes to {named}. Congratulations!", ping=winners)
```

- A job's parameters after the context are its payload. `draw.bind(giveaway=giveaway)` fixes them, and pyright checks the names and types. `tx.schedule(bound, at=...)` queues it with the transaction's writes (D31).
- A job's key is its handler and arguments. Scheduling the same draw again moves it instead of adding another, and `tx.unschedule(draw.bind(giveaway=...))` removes it.
- A job can run twice after a crash, so it locks the giveaway and checks its state first. The final post can still repeat if the process dies between the commit and the send.
- `ctx.actor` in a job is whoever scheduled it. `ctx.guild` is the server. If the bot has left it, the job is dropped.
- Messages mention nobody unless you name members with `ping=`. An `@everyone` in a prize stays plain text.

## 8. Cancelling: plan, then apply

```python
@plugin.action(risk=DESTRUCTIVE, needs="manage_messages")
async def cancel(ctx: Ctx, giveaway: int) -> str:
    """Cancel a running giveaway and its draw.

    Args:
        giveaway: The giveaway's number, from /giveaways list.
    """
    async with ctx.db.transaction() as tx:
        await tx.execute(SET_STATE, ctx.guild.id, giveaway, "cancelled")
        await tx.unschedule(draw.bind(giveaway=giveaway))
    return f"Cancelled giveaway {giveaway}."


@cancel.plan
async def plan_cancel(ctx: Ctx, giveaway: int) -> Diff:
    running = [g for g in await ctx.db.fetch(Running, RUNNING, ctx.guild.id) if g.id == giveaway]
    if not running:
        raise ActionError("No running giveaway has that number.")
    (found,) = running
    detail = f"{found.entrants} entrants"
    return Diff(entries=[DiffEntry(change="cancel", target=found.prize, detail=detail, key=found.id)])
```

- A destructive action needs a plan. Without one the load fails.
- The member first sees the plan and confirms it within 15 minutes. If anything it showed has changed by then, they get a fresh plan instead (D21).
- The apply runs as a job, and can read the confirmed plan as `ctx.diff`. Each entry's `key` carries what the apply needs, such as a row id, so it acts on exactly what the member saw.
- A parameter annotated `Context` is filled in by teabot. Every other parameter is an input.

## 9. Tests

```python
async def started(harness: PluginHarness, *, winners: int = 1, minutes: int = 30) -> tuple[FakeChannel, int]:
    channel = harness.guild.add_channel(FakeChannel())
    out = await harness.call(start, channel=channel, prize="A pet", winners=winners, minutes=minutes)
    return channel, out.giveaway


async def test_the_draw_announces_the_winners_when_time_is_up(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, giveaway = await started(harness, winners=2)
    players = [harness.guild.add_member(discord.Permissions.none()) for _ in range(3)]
    for player in players:
        assert await harness.as_member(player).call(enter, giveaway=giveaway) == "You're in. Good luck!"
    await harness.advance(minutes=31)
    await harness.run_jobs()
    pinged = channel.sent[-1].allowed_mentions.to_dict()["users"]
    assert len(pinged) == 2 and set(pinged) <= {p.id for p in players}


async def test_cancelling_shows_a_plan_and_stops_the_draw(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    channel, giveaway = await started(harness)
    plan = await harness.plan(cancel, giveaway=giveaway)
    assert [(e.change, e.target, e.detail) for e in plan.entries] == [("cancel", "A pet", "0 entrants")]
    await harness.confirm(plan)
    await harness.advance(minutes=31)
    await harness.run_jobs()
    assert len(channel.sent) == 1


async def test_the_excluded_role_cannot_enter(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(plugin)
    staff = harness.guild.add_role("staff")
    await harness.configure(Cfg(excluded_role=staff.id))
    _, giveaway = await started(harness)
    member = harness.guild.add_member(discord.Permissions.none(), roles=[staff])
    with pytest.raises(ActionFailed) as caught:
        await harness.as_member(member).call(enter, giveaway=giveaway)
    assert caught.value.public_message == "Your role cannot enter giveaways here."
```

- `teabot_harness` loads the plugin through the real loader and migrations into a fake server.
- `harness.call(start, ...)` runs the action through the real call path, permissions and audit included. Pyright checks the arguments against the function, and the result is a `Started`. It calls as the server's first member, who has Administrator. `harness.as_member(member).call(...)` calls as someone else.
- `harness.advance(minutes=31)` moves the clock for `ctx.now`, for `now()` in the plugin's SQL, and for when jobs fall due.
- `harness.plan(cancel, ...)` returns the plan, and `harness.confirm(plan)` confirms it and runs the apply.
- `harness.run_jobs()` runs every due job, and raises `JobFailed` with the job's own traceback when one fails.
- `harness.configure(Cfg(...))` sets config the way an admin would.
- The harness runs `teabot check` on the package when it loads the plugin. It refuses internal imports, clock reads that tests cannot move, `SET` in SQL and a README without "External connections".
- `test_giveaways_snapshot.py` fails when a command, an MCP tool or a job's payload changes, and prints the difference. Accept a change you meant with `pytest --teabot-accept`. A renamed parameter then never reaches servers by accident, where it would break queued jobs and the commands members know.

## 10. Growing past one file

Move `plugin = Plugin(...)` and `type Ctx` into `plugin.py`, and import them from every other module. teabot imports every module of the package when it loads the plugin, except `tests`, modules whose names start with `_`, and `__main__`. So actions in `actions.py` and jobs in `jobs.py` register themselves.

## 11. Ship it

- Restart teabot, then turn the plugin on in a server with `/plugins enable plugin:giveaways`.
- `uv run teabot check plugins/giveaways` runs the same checks as the harness, for CI.
- To publish it for other instances, give it a version, depend on a compatible teabot range such as `teabot>=1.1,<2`, and list every host it contacts in the README (D12, D14).
