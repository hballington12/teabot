"""teabot-polls, the plugin the tutorial builds. Imports only `teabot.sdk`.

- `polls.start` posts a poll with two to ten numbered options, and schedules the job that closes it.
- `polls.vote` records a member's one vote in a poll; voting again changes it. As the member types, it suggests
  the running polls, then the chosen poll's options.
- `polls.list` shows the running polls, with how many have voted.
- `polls.delete` deletes a poll and its votes, after a plan.
- The `close` job posts the results when time is up.
"""

# --8<-- [start:imports]
from datetime import datetime, timedelta
from typing import Annotated

from pydantic import BaseModel, Field

from teabot.sdk import (
    DESTRUCTIVE,
    READ,
    ActionError,
    Choice,
    Context,
    Diff,
    DiffEntry,
    Plugin,
    RoleRef,
    TextChannel,
    UntrustedText,
)

# --8<-- [end:imports]


# --8<-- [start:plugin]
class Cfg(BaseModel):
    default_minutes: int = Field(default=60, ge=1, le=10080)
    voter_role: RoleRef | None = None


plugin = Plugin("polls", config=Cfg, description="Polls that members vote in with buttons.")
type Ctx = Context[Cfg]
# --8<-- [end:plugin]

# --8<-- [start:queries]
START = """
INSERT INTO polls (guild_id, channel_id, question, options, ends_at) VALUES ($1, $2, $3, $4, $5) RETURNING id
"""
VOTE = """
WITH open AS (
    SELECT guild_id, id, options FROM polls
    WHERE guild_id = $1 AND id = $2 AND state = 'running' AND ends_at > now() AND $4 <= cardinality(options)
), earlier AS (
    SELECT choice FROM votes WHERE guild_id = $1 AND poll_id = $2 AND member_id = $3
), cast_vote AS (
    INSERT INTO votes (guild_id, poll_id, member_id, choice)
    SELECT guild_id, id, $3, $4 FROM open
    ON CONFLICT (guild_id, poll_id, member_id) DO UPDATE SET choice = EXCLUDED.choice
    RETURNING choice
)
SELECT (SELECT choice FROM earlier) AS earlier, open.options FROM open, cast_vote
"""
RUNNING = """
SELECT p.id, p.question, p.ends_at, count(v.member_id) AS voters
FROM polls p LEFT JOIN votes v ON v.guild_id = p.guild_id AND v.poll_id = p.id
WHERE p.guild_id = $1 AND p.state = 'running'
GROUP BY p.id ORDER BY p.ends_at
"""
LOCK_RUNNING = """
SELECT channel_id, question, options FROM polls WHERE guild_id = $1 AND id = $2 AND state = 'running' FOR UPDATE
"""
COUNTS = "SELECT choice, count(*) AS votes FROM votes WHERE guild_id = $1 AND poll_id = $2 GROUP BY choice"
CLOSE = "UPDATE polls SET state = 'closed' WHERE guild_id = $1 AND id = $2"
ONE = "SELECT id, question FROM polls WHERE guild_id = $1 AND id = $2"
OPTIONS = "SELECT options FROM polls WHERE guild_id = $1 AND id = $2 AND state = 'running'"
DELETE = "DELETE FROM polls WHERE guild_id = $1 AND id = $2"
# --8<-- [end:queries]


# --8<-- [start:start]
class Started(BaseModel):
    poll: int
    ends_at: datetime

    def render(self) -> str:
        return f"Poll {self.poll} started; it closes <t:{int(self.ends_at.timestamp())}:R>."


type Answer = Annotated[str, Field(min_length=1, max_length=100)]


@plugin.action(needs="manage_messages")
async def start(
    ctx: Ctx,
    channel: TextChannel,
    question: Annotated[str, Field(max_length=200)],
    options: Annotated[list[Answer], Field(min_length=2, max_length=10)],
    minutes: Annotated[int, Field(ge=1, le=10080)] | None = None,
) -> Started:
    """Start a poll.

    Args:
        channel: Where to post the poll.
        question: What the poll asks.
        options: The answers to choose from.
        minutes: How long it runs; the server's default if left out.
    """
    ends_at = ctx.now + timedelta(minutes=minutes or ctx.config.default_minutes)
    async with ctx.db.transaction() as tx:
        poll = await tx.fetchval(int, START, ctx.guild.id, channel.id, question, options, ends_at)
        await tx.schedule(close.bind(poll=poll), at=ends_at)
    numbered = "\n".join(f"{n}. {option}" for n, option in enumerate(options, start=1))
    await channel.send(f"**Poll {poll}: {question}**\n{numbered}\nVote with `/polls vote poll:{poll}`.")
    return Started(poll=poll, ends_at=ends_at)


# --8<-- [end:start]


# --8<-- [start:vote]
class Voted(BaseModel):
    earlier: int | None
    options: list[str]


@plugin.action()
async def vote(ctx: Ctx, poll: int, option: Annotated[int, Field(ge=1, le=10)]) -> str:
    """Vote in a running poll, or change your vote.

    Args:
        poll: The poll's number, from /polls list.
        option: The number of the option you choose.
    """
    role = ctx.config.voter_role
    if role is not None:
        member = await ctx.guild.get_member(ctx.actor.user_id)
        if member is None or role not in member.role_ids:
            raise ActionError("You need the voter role to vote here.")
    voted = await ctx.db.fetchrow(Voted, VOTE, ctx.guild.id, poll, ctx.actor.user_id, option)
    if voted is None:
        raise ActionError("That poll is not running, or has no option with that number.")
    chosen = f"{option}: {voted.options[option - 1]}"
    if voted.earlier is None:
        return f"You voted for option {chosen}."
    if voted.earlier == option:
        return f"Your vote is still option {chosen}."
    return (
        f"You changed your vote from option {voted.earlier}: {voted.options[voted.earlier - 1]} to {chosen}."
    )


# --8<-- [end:vote]


# --8<-- [start:list]
class Running(BaseModel):
    id: int
    question: UntrustedText
    ends_at: datetime
    voters: int


@plugin.action(risk=READ, reply="public")
async def list_(ctx: Ctx) -> list[Running]:
    """The running polls."""
    return await ctx.db.fetch(Running, RUNNING, ctx.guild.id)


# --8<-- [end:list]


# --8<-- [start:suggest]
@vote.autocomplete("poll")
async def running_polls(ctx: Ctx, typed: str) -> list[Choice[int]]:
    polls = await ctx.db.fetch(Running, RUNNING, ctx.guild.id)
    shown = [Choice(f"{p.id}: {p.question}"[:100], p.id) for p in polls]
    return [c for c in shown if typed.lower() in c.name.lower()]


@vote.autocomplete("option")
async def poll_options(ctx: Ctx, typed: str) -> list[Choice[int]]:
    poll = ctx.filled.get("poll")
    if not isinstance(poll, int):
        return []
    options = await ctx.db.fetchval(list[str] | None, OPTIONS, ctx.guild.id, poll)
    shown = [Choice(f"{n}: {option}"[:100], n) for n, option in enumerate(options or [], start=1)]
    return [c for c in shown if typed.lower() in c.name.lower()]


# --8<-- [end:suggest]


# --8<-- [start:close]
class Open(BaseModel):
    channel_id: int
    question: str
    options: list[str]


class Count(BaseModel):
    choice: int
    votes: int


@plugin.job
async def close(ctx: Ctx, poll: int) -> None:
    async with ctx.db.transaction() as tx:
        found = await tx.fetchrow(Open, LOCK_RUNNING, ctx.guild.id, poll)
        if found is None:
            return
        counts = {c.choice: c.votes for c in await tx.fetch(Count, COUNTS, ctx.guild.id, poll)}
        await tx.execute(CLOSE, ctx.guild.id, poll)
        lines = [f"{n}. {option}: {counts.get(n, 0)}" for n, option in enumerate(found.options, start=1)]
        await tx.send(found.channel_id, f"**Poll {poll} has closed: {found.question}**\n" + "\n".join(lines))


# --8<-- [end:close]


# --8<-- [start:delete]
class Found(BaseModel):
    id: int
    question: UntrustedText


@plugin.action(risk=DESTRUCTIVE, needs="manage_messages")
async def delete(ctx: Ctx, poll: int) -> str:
    """Delete a poll and its votes.

    Args:
        poll: The poll's number, from /polls list.
    """
    async with ctx.db.transaction() as tx:
        await tx.execute(DELETE, ctx.guild.id, poll)
        await tx.unschedule(close.bind(poll=poll))
    return f"Deleted poll {poll}."


@delete.plan
async def plan_delete(ctx: Ctx, poll: int) -> Diff:
    found = await ctx.db.fetchrow(Found, ONE, ctx.guild.id, poll)
    if found is None:
        raise ActionError("No poll has that number.")
    return Diff(entries=[DiffEntry(change="delete", target=found.question, key=found.id)])


# --8<-- [end:delete]
