"""teapot-devtools: a development-only plugin that exercises the core (WP2.9). Never installed in production.

- `devtools.note` writes to the plugin's own table in a transaction.
- `devtools.peek_core` tries to read the core schema and reports the refusal the plugin role gets (D9).
- Setting `TEAPOT_DEVTOOLS_FAIL_SETUP=1` makes `setup` fail, to see a failed plugin reported (D14).
"""

import os
from pathlib import Path

import discord
from pydantic import BaseModel, Field

from teapot.sdk import ActionContext, ActionError, ActionSpec, Manifest, Registrar, Risk

FAIL_SETUP = "TEAPOT_DEVTOOLS_FAIL_SETUP"
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


plugin = Devtools()
