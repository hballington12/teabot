"""teabot-giveaways: members enter, and winners are drawn when time is up. Imports only `teabot.sdk`.

- `giveaways.start` announces a giveaway and schedules its draw.
- `giveaways.enter` enters the calling member.
- `giveaways.list` shows the running giveaways.
- `giveaways.cancel` cancels one and its draw, after a plan.
- The `draw` job picks the winners and announces them.
"""

from datetime import datetime, timedelta
from typing import Annotated

from pydantic import BaseModel, Field

from teabot.sdk import (
    DESTRUCTIVE,
    READ,
    ActionError,
    Context,
    Diff,
    DiffEntry,
    Plugin,
    RoleRef,
    TextChannel,
    UntrustedText,
)


class Cfg(BaseModel):
    default_minutes: int = Field(default=60, ge=1, le=10080)
    excluded_role: RoleRef | None = None


plugin = Plugin("giveaways", config=Cfg)
type Ctx = Context[Cfg]


class Started(BaseModel):
    giveaway: int
    ends_at: datetime

    def render(self) -> str:
        return f"Giveaway {self.giveaway} started; it ends <t:{int(self.ends_at.timestamp())}:R>."


class Running(BaseModel):
    id: int
    prize: UntrustedText
    ends_at: datetime
    entrants: int


class Drawable(BaseModel):
    channel_id: int
    prize: str
    winners: int


START = """
INSERT INTO giveaways (guild_id, channel_id, prize, winners, ends_at) VALUES ($1, $2, $3, $4, $5) RETURNING id
"""
RUNNING = """
SELECT g.id, g.prize, g.ends_at, count(e.member_id) AS entrants
FROM giveaways g LEFT JOIN entries e ON e.guild_id = g.guild_id AND e.giveaway_id = g.id
WHERE g.guild_id = $1 AND g.state = 'running'
GROUP BY g.id ORDER BY g.ends_at
"""
ENTER = """
INSERT INTO entries (guild_id, giveaway_id, member_id)
SELECT guild_id, id, $3 FROM giveaways WHERE guild_id = $1 AND id = $2 AND state = 'running' AND ends_at > now()
ON CONFLICT DO NOTHING
"""
LOCK_RUNNING = """
SELECT channel_id, prize, winners FROM giveaways WHERE guild_id = $1 AND id = $2 AND state = 'running' FOR UPDATE
"""
PICK = """
SELECT member_id FROM entries WHERE guild_id = $1 AND giveaway_id = $2 ORDER BY random() LIMIT $3
"""
MARK_WON = "UPDATE entries SET won = true WHERE guild_id = $1 AND giveaway_id = $2 AND member_id = ANY($3)"
SET_STATE = "UPDATE giveaways SET state = $3 WHERE guild_id = $1 AND id = $2 AND state = 'running'"


def announcement(prize: str, giveaway: int, ends_at: datetime) -> str:
    return (
        f"**Giveaway: {prize}**\nEnter with `/giveaways enter giveaway:{giveaway}`. "
        f"Winners are drawn <t:{int(ends_at.timestamp())}:R>."
    )


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


@plugin.action(risk=READ, reply="public")
async def list_(ctx: Ctx) -> list[Running]:
    """The running giveaways."""
    return await ctx.db.fetch(Running, RUNNING, ctx.guild.id)


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


@plugin.job
async def draw(ctx: Ctx, giveaway: int) -> None:
    async with ctx.db.transaction() as tx:
        row = await tx.fetchrow(Drawable, LOCK_RUNNING, ctx.guild.id, giveaway)
        if row is None:
            return
        winners = await tx.fetch(int, PICK, ctx.guild.id, giveaway, row.winners)
        await tx.execute(MARK_WON, ctx.guild.id, giveaway, winners)
        await tx.execute(SET_STATE, ctx.guild.id, giveaway, "drawn")
        if not winners:
            await tx.send(row.channel_id, f"Nobody entered the giveaway for **{row.prize}**.")
            return
        named = ", ".join(f"<@{w}>" for w in winners)
        await tx.send(row.channel_id, f"**{row.prize}** goes to {named}. Congratulations!", ping=winners)
