"""teabot-tickets: queues of items members claim, and handlers who accept or reject the claims (events-and-tickets.md).
Imports only `teabot.sdk`.

- Queues, in this module: `tickets.queue_add`, `tickets.queue_edit`, `tickets.queue_remove` and `tickets.queues`.
- Tickets, in `items`: `tickets.create`, `tickets.cancel`, `tickets.reopen` and `tickets.list`.
- Claims, in `claims`: `tickets.claim`, `tickets.withdraw`, `tickets.mine`, `tickets.waiting`, `tickets.accept`,
  `tickets.reject`, `tickets.revoke`, and `tickets.grant`, for a ticket given to a member who didn't claim it.
- The board, in `board`: `tickets.post`, and the form its Claim button opens.

It stops at ticketing: it changes no roles and links nothing. What follows an accept belongs to whoever subscribes to
its events, `tickets.accepted`, `tickets.rejected` and `tickets.revoked`, each about one ticket. Every write to a
ticket or its claims locks the ticket's row first, in ascending ID order, so for one ticket a later event always has
a higher ID.
"""

from datetime import timedelta
from typing import Annotated, Any

from pydantic import BaseModel, Field

from teabot.sdk import (
    DESTRUCTIVE,
    READ,
    ActionError,
    Choice,
    Context,
    Diff,
    DiffEntry,
    EmptyConfig,
    Event,
    Member,
    MemberRef,
    Plugin,
    Role,
    TextChannel,
    UntrustedText,
)


class Accepted(BaseModel):
    queue: int
    queue_name: UntrustedText
    ticket: int
    key: str | None
    title: UntrustedText
    claim: int
    note: UntrustedText
    claimant: MemberRef


class Rejected(BaseModel):
    queue: int
    queue_name: UntrustedText
    ticket: int
    key: str | None
    title: UntrustedText
    claim: int
    note: UntrustedText
    claimant: MemberRef
    reason: UntrustedText


class Revoked(BaseModel):
    queue: int
    queue_name: UntrustedText
    ticket: int
    key: str | None
    title: UntrustedText
    claim: int | None
    note: UntrustedText | None
    claimant: MemberRef | None
    reason: UntrustedText


plugin = Plugin(
    "tickets",
    description="Queues of items members claim, such as game accounts, and handlers who accept or reject claims.",
    emits=[
        Event("accepted", Accepted, "A claim on a ticket was accepted, which closed the ticket"),
        Event(
            "rejected",
            Rejected,
            "A claim on a ticket was rejected, by a handler or because another was accepted",
        ),
        Event("revoked", Revoked, "An accepted claim was undone, which reopened its ticket"),
    ],
)
type Ctx = Context[EmptyConfig]

OPEN_MAX = 10_000
WAITING_MAX = 10
MANAGERS = frozenset({"manage_guild", "administrator"})

type Name = Annotated[str, Field(min_length=1, max_length=100)]
Roles = Annotated[list[Role], Field(max_length=10)]

QUEUE = """
SELECT id, name, channel_id, claimers, handlers, per_day, handlers_channel_id, board_post FROM queues
WHERE guild_id = $1 AND id = $2
"""


class Queue(BaseModel):
    id: int
    name: str
    channel_id: int
    claimers: list[int]
    handlers: list[int]
    per_day: int
    handlers_channel_id: int | None
    board_post: int | None


class QueueListed(BaseModel):
    id: int
    name: UntrustedText
    channel_id: int
    open: int
    waiting: int

    def render(self) -> str:
        return (
            f"{self.id}: {self.name} in <#{self.channel_id}>, {self.open} open, {self.waiting} claims waiting"
        )


REFRESH_AFTER = timedelta(minutes=1)


async def refresh_board(ctx: Ctx, tx: Any, queue: int) -> None:
    """Refresh the queue's board a minute from now. The job is keyed by queue, so a burst of changes makes one
    edit."""
    await tx.schedule("refresh", at=ctx.now + REFRESH_AFTER, payload={"queue": queue}, key=f"refresh:{queue}")


async def member_of(ctx: Ctx) -> Member:
    member = await ctx.guild.get_member(ctx.actor.user_id)
    if member is None:
        raise ActionError("You are not in this server.")
    return member


def manages(ctx: Ctx, member: Member) -> bool:
    """Whether the member has Manage Server, or owns the server."""
    return member.id == ctx.guild.owner_id or any(r.permissions & MANAGERS for r in member.roles)


def handles(ctx: Ctx, member: Member, queue: Queue) -> bool:
    return manages(ctx, member) or bool(member.role_ids & set(queue.handlers))


def may_claim(member: Member, queue: Queue) -> bool:
    return not queue.claimers or bool(member.role_ids & set(queue.claimers))


async def queue_of(ctx: Ctx, queue: int, *, within: Any = None, lock: bool = False) -> Queue:
    """The queue, read within `within`, an open transaction, when given, and locked with `lock`; else
    `ActionError`."""
    db = within or ctx.db
    found = await db.fetchrow(Queue, QUEUE + (" FOR UPDATE" if lock else ""), ctx.guild.id, queue)
    if found is None:
        raise ActionError(f"There is no ticket queue {queue} here. /tickets queues lists them.")
    return found


async def handled(ctx: Ctx, queue: int, *, within: Any = None, lock: bool = False) -> Queue:
    """The queue, once the member asking handles it; else `ActionError`."""
    found = await queue_of(ctx, queue, within=within, lock=lock)
    if not handles(ctx, await member_of(ctx), found):
        raise ActionError(f"Only {found.name}'s handlers may do that.")
    return found


@plugin.action(needs="manage_guild")
async def queue_add(
    ctx: Ctx,
    name: Name,
    channel: TextChannel,
    handlers: Roles,
    claimers: Roles | None = None,
    per_day: Annotated[int, Field(ge=1, le=100)] = 10,
    handlers_channel: TextChannel | None = None,
) -> str:
    """Make a ticket queue: one kind of item members claim, and the roles that settle the claims.

    Args:
        name: Such as "Link your account"
        channel: Where its board is posted
        handlers: Roles that may create tickets and accept or reject claims
        claimers: Roles that may claim; everyone when left out
        per_day: How many claims a member may make in it each day
        handlers_channel: Where each new claim is posted for handlers, with Accept and Reject buttons
    """
    made = await ctx.db.fetchval(
        int,
        "INSERT INTO queues (guild_id, name, channel_id, claimers, handlers, per_day, handlers_channel_id) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id",
        ctx.guild.id,
        name,
        channel.id,
        [r.id for r in claimers or []],
        [r.id for r in handlers],
        per_day,
        handlers_channel.id if handlers_channel else None,
    )
    return f"Made ticket queue {made}, {name}. Post its board with /tickets post queue:{made}."


@plugin.action(needs="manage_guild")
async def queue_edit(
    ctx: Ctx,
    queue: int,
    name: Name | None = None,
    channel: TextChannel | None = None,
    handlers: Roles | None = None,
    claimers: Roles | None = None,
    per_day: Annotated[int, Field(ge=1, le=100)] | None = None,
    handlers_channel: TextChannel | None = None,
) -> str:
    """Change a ticket queue. What you leave out stays as it is.

    Args:
        queue: The queue's number
        name: Its new name
        channel: Where its board is posted
        handlers: Roles that may create tickets and settle claims
        claimers: Roles that may claim
        per_day: How many claims a member may make in it each day
        handlers_channel: Where new claims are posted for handlers
    """
    async with ctx.db.transaction() as tx:
        found = await queue_of(ctx, queue, within=tx, lock=True)
        await tx.execute(
            "UPDATE queues SET name = $3, channel_id = $4, handlers = $5, claimers = $6, per_day = $7, "
            "handlers_channel_id = $8 WHERE guild_id = $1 AND id = $2",
            ctx.guild.id,
            queue,
            name or found.name,
            channel.id if channel else found.channel_id,
            [r.id for r in handlers] if handlers is not None else found.handlers,
            [r.id for r in claimers] if claimers is not None else found.claimers,
            per_day or found.per_day,
            handlers_channel.id if handlers_channel else found.handlers_channel_id,
        )
    return f"Changed ticket queue {queue}."


@plugin.action(risk=DESTRUCTIVE, needs="manage_guild")
async def queue_remove(ctx: Ctx, queue: int) -> str:
    """Delete a ticket queue, with its tickets and claims. It emits no events, so what subscribers built from its
    accepts stays.

    Args:
        queue: The queue's number
    """
    found = await queue_of(ctx, queue)
    async with ctx.db.transaction() as tx:
        if found.board_post is not None:
            await tx.delete(found.board_post)
        await tx.execute("DELETE FROM queues WHERE guild_id = $1 AND id = $2", ctx.guild.id, queue)
    return f"Deleted ticket queue {queue}, {found.name}."


@queue_remove.plan
async def plan_queue_remove(ctx: Ctx, queue: int) -> Diff:
    found = await queue_of(ctx, queue)
    counts = await ctx.db.fetchrow(
        "SELECT count(*) FILTER (WHERE state = 'open') AS open, count(*) AS total FROM tickets "
        "WHERE guild_id = $1 AND queue_id = $2",
        ctx.guild.id,
        queue,
    )
    assert counts is not None
    detail = f"{counts['total']} tickets, {counts['open']} of them open, and their claims"
    return Diff(entries=[DiffEntry(change="delete", target=found.name, detail=detail, key=queue)])


@plugin.action(risk=READ)
async def queues(ctx: Ctx) -> list[QueueListed]:
    """The server's ticket queues."""
    return await ctx.db.fetch(
        QueueListed,
        """
        SELECT q.id, q.name, q.channel_id,
               (SELECT count(*) FROM tickets t WHERE t.guild_id = q.guild_id AND t.queue_id = q.id
                AND t.state = 'open') AS open,
               (SELECT count(*) FROM claims c JOIN tickets t ON t.guild_id = c.guild_id AND t.id = c.ticket_id
                WHERE c.guild_id = q.guild_id AND t.queue_id = q.id AND c.state = 'waiting') AS waiting
        FROM queues q WHERE q.guild_id = $1 ORDER BY q.id
        """,
        ctx.guild.id,
    )


async def queue_choices(ctx: Ctx, typed: str) -> list[Choice[int]]:
    rows = await ctx.db.fetch("SELECT id, name FROM queues WHERE guild_id = $1 ORDER BY id", ctx.guild.id)
    return [
        Choice(f"{r['id']}: {r['name']}"[:100], int(r["id"]))
        for r in rows
        if typed.lower() in f"{r['id']} {r['name']}".lower()
    ][:25]


queue_edit.autocomplete("queue")(queue_choices)
queue_remove.autocomplete("queue")(queue_choices)

# The other parts register their actions on the plugin.
from . import board as board  # noqa: E402
from . import claims as claims  # noqa: E402
from . import items as items  # noqa: E402
