"""teabot-devtools: a development-only plugin that exercises the core. Never installed in production.

- `devtools.note` writes to the plugin's own table in a transaction.
- `devtools.peek_core` tries to read the core schema and reports the refusal the plugin role gets (D9).
- `devtools.clear_notes` is destructive: it plans, then clears notes one at a time and reports progress (D21).
- Setting `TEABOT_DEVTOOLS_FAIL_SETUP=1` makes `setup` fail, to see a failed plugin reported (D14).
"""

import asyncio
import os
from typing import Annotated

from pydantic import BaseModel, Field

from teabot.sdk import (
    DESTRUCTIVE,
    READ,
    ActionError,
    Context,
    Diff,
    DiffEntry,
    EmptyConfig,
    Plugin,
    Registrar,
)

FAIL_SETUP = "TEABOT_DEVTOOLS_FAIL_SETUP"


class Devtools(Plugin[EmptyConfig]):
    """The plugin, with a switch that makes its setup fail."""

    def setup(self, registrar: Registrar) -> None:
        if os.environ.get(FAIL_SETUP) == "1":
            raise RuntimeError(f"{FAIL_SETUP} is set")
        super().setup(registrar)


plugin = Devtools("devtools")
type Ctx = Context[EmptyConfig]


class Noted(BaseModel):
    notes: int


class Peeked(BaseModel):
    refusal: str


class Cleared(BaseModel):
    cleared: int


@plugin.action()
async def note(ctx: Ctx, text: Annotated[str, Field(max_length=200)]) -> Noted:
    """Note something down.

    Args:
        text: What to note down
    """
    async with ctx.db.transaction() as tx:
        await tx.execute("INSERT INTO notes (guild_id, text) VALUES ($1, $2)", ctx.guild.id, text)
        count = await tx.fetchval(int, "SELECT count(*) FROM notes WHERE guild_id = $1", ctx.guild.id)
    return Noted(notes=count)


@plugin.action(risk=READ, needs="manage_guild")
async def peek_core(ctx: Ctx) -> Peeked:
    """Try to read the core schema, and report the refusal. Reading it would mean role isolation (D9) is
    broken."""
    try:
        await ctx.db.fetchval("SELECT count(*) FROM core.jobs")
    except Exception as exc:
        return Peeked(refusal=str(exc))
    raise ActionError("the plugin role could read the core schema: role isolation (D9) is broken")


MATCHING = """
SELECT ctid::text AS row, text FROM notes WHERE guild_id = $1 AND strpos(text, $2) > 0 ORDER BY created_at, text
"""


class Match(BaseModel):
    row: str
    text: str


@plugin.action(risk=DESTRUCTIVE, needs="manage_guild")
async def clear_notes(
    ctx: Ctx,
    containing: Annotated[str, Field(max_length=200)] = "",
    seconds_each: Annotated[int, Field(ge=0, le=5)] = 0,
) -> Cleared:
    """Clear notes, after showing which.

    Args:
        containing: Only notes containing this; empty for all
        seconds_each: A pause after each note, to watch progress
    """
    rows = [str(entry.key) for entry in ctx.diff.entries]
    for done, row in enumerate(rows, start=1):
        await ctx.db.execute(
            "DELETE FROM notes WHERE guild_id = $1 AND ctid = $2::text::tid", ctx.guild.id, row
        )
        await ctx.report({"done": done, "total": len(rows)})
        await asyncio.sleep(seconds_each)
    return Cleared(cleared=len(rows))


@clear_notes.plan
async def plan_clear(ctx: Ctx, containing: str = "", seconds_each: int = 0) -> Diff:
    rows = await ctx.db.fetch(Match, MATCHING, ctx.guild.id, containing)
    return Diff(entries=[DiffEntry(change="remove", target=r.text, key=r.row) for r in rows])
