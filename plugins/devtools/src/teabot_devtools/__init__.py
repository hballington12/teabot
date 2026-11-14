"""teabot-devtools: a development-only plugin that exercises the core. Never installed in production.

- `devtools.note` writes to the plugin's own table in a transaction.
- `devtools.peek_core` tries to read the core schema and reports the refusal the plugin role gets (D9).
- `devtools.clear_notes` is destructive: it plans, then clears notes one at a time and reports progress (D21).
- Setting `TEABOT_DEVTOOLS_FAIL_SETUP=1` makes `setup` fail, to see a failed plugin reported (D14).
"""

import asyncio
import os
from pathlib import Path

import discord
from pydantic import BaseModel, Field

from teabot.sdk import ActionContext, ActionError, ActionSpec, Diff, DiffEntry, Manifest, Registrar, Risk

FAIL_SETUP = "TEABOT_DEVTOOLS_FAIL_SETUP"
MANAGE_SERVER = discord.Permissions(manage_guild=True)


class Note(BaseModel):
    text: str = Field(max_length=200, description="What to note down")


class Noted(BaseModel):
    notes: int


async def note(ctx: ActionContext, data: Note) -> Noted:
    async with ctx.db.transaction() as tx:
        await tx.execute("INSERT INTO notes (guild_id, text) VALUES ($1, $2)", ctx.guild.id, data.text)
        count: int = await tx.fetchval("SELECT count(*) FROM notes WHERE guild_id = $1", ctx.guild.id)
    return Noted(notes=count)


class Peek(BaseModel):
    pass


class Peeked(BaseModel):
    refusal: str


async def peek_core(ctx: ActionContext, _data: Peek) -> Peeked:
    """Report the refusal. Reading core succeeding would mean the role isolation of D9 is broken."""
    try:
        await ctx.db.fetchval("SELECT count(*) FROM core.jobs")
    except Exception as exc:
        return Peeked(refusal=str(exc))
    raise ActionError("the plugin role could read the core schema: role isolation (D9) is broken")


class ClearNotes(BaseModel):
    containing: str = Field(
        default="", max_length=200, description="Only notes containing this; empty for all"
    )
    seconds_each: int = Field(default=0, ge=0, le=5, description="A pause after each note, to watch progress")


class Cleared(BaseModel):
    cleared: int


MATCHING = """
SELECT ctid::text AS row, text FROM notes WHERE guild_id = $1 AND strpos(text, $2) > 0 ORDER BY created_at, text
"""


async def plan_clear(ctx: ActionContext, data: ClearNotes) -> Diff:
    rows = await ctx.db.fetch(MATCHING, ctx.guild.id, data.containing)
    return Diff(entries=[DiffEntry(change="remove", target=r["text"]) for r in rows])


async def clear_notes(ctx: ActionContext, data: ClearNotes) -> Cleared:
    """A bulk change in steps, so a plan's apply has progress to report (D21)."""
    rows = await ctx.db.fetch(MATCHING, ctx.guild.id, data.containing)
    for done, row in enumerate(rows, start=1):
        await ctx.db.execute(
            "DELETE FROM notes WHERE guild_id = $1 AND ctid = $2::text::tid", ctx.guild.id, row["row"]
        )
        await ctx.report({"done": done, "total": len(rows)})
        await asyncio.sleep(data.seconds_each)
    return Cleared(cleared=len(rows))


class Devtools:
    manifest = Manifest("devtools", "0.1.0", migrations=Path(__file__).parent / "migrations")

    def setup(self, registrar: Registrar) -> None:
        if os.environ.get(FAIL_SETUP) == "1":
            raise RuntimeError(f"{FAIL_SETUP} is set")
        registrar.action(ActionSpec("devtools.note", "Note something down", Note, Noted, Risk.WRITE, note))
        registrar.action(
            ActionSpec(
                "devtools.peek_core",
                "Try to read the core schema",
                Peek,
                Peeked,
                Risk.READ,
                peek_core,
                default_permissions=MANAGE_SERVER,
            )
        )
        registrar.action(
            ActionSpec(
                "devtools.clear_notes",
                "Clear notes, after showing which",
                ClearNotes,
                Cleared,
                Risk.DESTRUCTIVE,
                clear_notes,
                plan=plan_clear,
                default_permissions=MANAGE_SERVER,
            )
        )


plugin = Devtools()
