"""Tickets: creating them in batches kept in step by key, cancelling and reopening them, and listing them.

`tickets.create` updates the ticket a key already names, in any state, and never reopens it, so a program repeats a
call safely. It reports each ticket as created, updated or unchanged, so a program sends only what changed.
"""

from datetime import datetime, timedelta
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from teabot.sdk import READ, ActionError, MemberRef, Surface, UntrustedText

from . import OPEN_MAX, Ctx, handled, plugin, refresh_board
from .claims import reject_waiting

BATCH = 25
TITLE_MAX = 100
BODY_MAX = 1000
PAGE = 50

type Title = Annotated[str, Field(min_length=1, max_length=TITLE_MAX)]
type Key = Annotated[str, Field(min_length=1, max_length=100)]
type Body = Annotated[str, Field(max_length=BODY_MAX)]

UPSERT = """
INSERT INTO tickets (guild_id, queue_id, title, body, key) VALUES ($1, $2, $3, $4, $5)
ON CONFLICT (guild_id, queue_id, key) WHERE key IS NOT NULL DO UPDATE
SET title = EXCLUDED.title, body = EXCLUDED.body, updated_at = now()
WHERE tickets.title IS DISTINCT FROM EXCLUDED.title OR tickets.body IS DISTINCT FROM EXCLUDED.body
RETURNING id, state, xmax = 0 AS made
"""
BY_KEY = "SELECT id, state FROM tickets WHERE guild_id = $1 AND queue_id = $2 AND key = $3"
TICKET = """
SELECT t.id, t.queue_id, t.title, t.key, t.state, t.resolution FROM tickets t WHERE t.guild_id = $1 AND t.id = $2
"""


class Made(BaseModel):
    id: int
    key: str | None
    state: str
    outcome: Literal["created", "updated", "unchanged"]


class Created(BaseModel):
    tickets: list[Made]

    def render(self) -> str:
        counts = {
            o: sum(1 for t in self.tickets if t.outcome == o) for o in ("created", "updated", "unchanged")
        }
        return ", ".join(f"{n} {o}" for o, n in counts.items() if n) or "Nothing to create."


@plugin.action(surfaces=Surface.MCP | Surface.SERVICE | Surface.WEB)
async def create(
    ctx: Ctx,
    queue: int,
    titles: Annotated[list[Title], Field(min_length=1, max_length=BATCH)],
    keys: Annotated[list[Key], Field(max_length=BATCH)] | None = None,
    bodies: Annotated[list[Body], Field(max_length=BATCH)] | None = None,
) -> Created:
    """Create up to 25 tickets in a queue. A ticket whose key the queue already has updates that ticket, whatever
    its state, and never reopens it.

    Args:
        queue: The queue's number
        titles: Each ticket's title, such as an account's name
        keys: Your own reference for each ticket, in the same order, such as an account's ID
        bodies: Each ticket's details, in the same order, such as evidence handlers see
    """
    if keys is not None and len(keys) != len(titles):
        raise ActionError("Give one key for each title, or none.")
    if bodies is not None and len(bodies) != len(titles):
        raise ActionError("Give one body for each title, or none.")
    if keys is not None and len(set(keys)) != len(keys):
        raise ActionError("Each key appears once in a call.")
    made: list[Made] = []
    async with ctx.db.transaction() as tx:
        found = await handled(ctx, queue, within=tx, lock=True)
        open_now = await tx.fetchval(
            int,
            "SELECT count(*) FROM tickets WHERE guild_id = $1 AND queue_id = $2 AND state = 'open'",
            ctx.guild.id,
            queue,
        )
        if open_now + len(titles) > OPEN_MAX:
            raise ActionError(f"A queue holds at most {OPEN_MAX:,} open tickets.")
        for n, title in enumerate(titles):
            key = keys[n] if keys else None
            body = bodies[n] if bodies else ""
            row = await tx.fetchrow(UPSERT, ctx.guild.id, queue, title, body, key)
            if row is not None:
                outcome: Literal["created", "updated", "unchanged"] = "created" if row["made"] else "updated"
                made.append(Made(id=row["id"], key=key, state=row["state"], outcome=outcome))
            else:
                same = await tx.fetchrow(BY_KEY, ctx.guild.id, queue, key)
                assert same is not None
                made.append(Made(id=same["id"], key=key, state=same["state"], outcome="unchanged"))
        if any(m.outcome == "created" for m in made):
            await refresh_board(ctx, tx, found.id)
    return Created(tickets=made)


@plugin.action()
async def cancel(ctx: Ctx, ticket: int, reason: Annotated[str, Field(max_length=200)] = "") -> str:
    """Cancel an open ticket. Its waiting claims are rejected.

    Args:
        ticket: The ticket's number
        reason: Why, which claimants and subscribers see
    """
    async with ctx.db.transaction() as tx:
        row = await tx.fetchrow(TICKET + " FOR UPDATE", ctx.guild.id, ticket)
        if row is None:
            raise ActionError(f"There is no ticket {ticket} here.")
        await handled(ctx, int(row["queue_id"]), within=tx)
        if row["state"] != "open":
            raise ActionError(f"Ticket {ticket} is already closed.")
        await tx.execute(
            "UPDATE tickets SET state = 'closed', resolution = 'cancelled', closed_at = now(), updated_at = now() "
            "WHERE guild_id = $1 AND id = $2",
            ctx.guild.id,
            ticket,
        )
        await reject_waiting(ctx, tx, ticket, None, reason or "the ticket was cancelled")
        await refresh_board(ctx, tx, int(row["queue_id"]))
    return f"Cancelled ticket {ticket}, {row['title']}."


@plugin.action()
async def reopen(ctx: Ctx, ticket: int) -> str:
    """Reopen a cancelled ticket. An accepted one is reopened only by /tickets revoke.

    Args:
        ticket: The ticket's number
    """
    async with ctx.db.transaction() as tx:
        row = await tx.fetchrow(TICKET + " FOR UPDATE", ctx.guild.id, ticket)
        if row is None:
            raise ActionError(f"There is no ticket {ticket} here.")
        await handled(ctx, int(row["queue_id"]), within=tx)
        if row["state"] == "open":
            raise ActionError(f"Ticket {ticket} is open already.")
        if row["resolution"] == "accepted":
            raise ActionError(f"Ticket {ticket} was accepted. Undo that with /tickets revoke.")
        await tx.execute(
            "UPDATE tickets SET state = 'open', resolution = NULL, closed_at = NULL, updated_at = now() "
            "WHERE guild_id = $1 AND id = $2",
            ctx.guild.id,
            ticket,
        )
        await refresh_board(ctx, tx, int(row["queue_id"]))
    return f"Reopened ticket {ticket}, {row['title']}."


class ClaimShown(BaseModel):
    id: int
    member: MemberRef
    note: UntrustedText
    state: str
    reason: UntrustedText | None


class TicketShown(BaseModel):
    id: int
    title: UntrustedText
    body: UntrustedText
    key: str | None
    state: str
    resolution: str | None
    updated_at: datetime
    claims: list[ClaimShown]


class TicketPage(BaseModel):
    tickets: list[TicketShown]
    page: int
    pages: int


LIST = """
SELECT id, title, body, key, state, resolution, updated_at FROM tickets
WHERE guild_id = $1 AND queue_id = $2
  AND ($3::text IS NULL OR state = $3) AND ($4::text IS NULL OR key = $4)
  AND ($5::timestamptz IS NULL OR updated_at > $5)
  AND ($6::bigint IS NULL OR EXISTS (
      SELECT 1 FROM claims c WHERE c.guild_id = tickets.guild_id AND c.ticket_id = tickets.id AND c.member = $6))
ORDER BY id LIMIT $7 OFFSET $8
"""
COUNT = """
SELECT count(*) FROM tickets
WHERE guild_id = $1 AND queue_id = $2
  AND ($3::text IS NULL OR state = $3) AND ($4::text IS NULL OR key = $4)
  AND ($5::timestamptz IS NULL OR updated_at > $5)
  AND ($6::bigint IS NULL OR EXISTS (
      SELECT 1 FROM claims c WHERE c.guild_id = tickets.guild_id AND c.ticket_id = tickets.id AND c.member = $6))
"""
CLAIMS_OF = """
SELECT id, ticket_id, member, note, state, reason FROM claims WHERE guild_id = $1 AND ticket_id = ANY($2::bigint[])
ORDER BY id
"""


@plugin.action(risk=READ)
async def list_(
    ctx: Ctx,
    queue: int,
    state: Literal["open", "closed"] | None = None,
    key: Key | None = None,
    claimant: MemberRef | None = None,
    changed_since: Annotated[str, Field(max_length=40)] | None = None,
    page: Annotated[int, Field(ge=1)] = 1,
) -> TicketPage:
    """A queue's tickets, with their claims, for its handlers. Programs reconcile against it.

    Args:
        queue: The queue's number
        state: Only open or only closed tickets
        key: Only the ticket with this key
        claimant: Only tickets this member claimed
        changed_since: Only tickets changed after this time, such as 2026-11-20T09:00:00Z
        page: Which page of 50
    """
    await handled(ctx, queue)
    since = None
    if changed_since:
        try:
            since = datetime.fromisoformat(changed_since)
        except ValueError:
            raise ActionError("changed_since is a time such as 2026-11-20T09:00:00Z.") from None
    args = (ctx.guild.id, queue, state, key, claimant, since)
    total = await ctx.db.fetchval(int, COUNT, *args)
    rows = await ctx.db.fetch(LIST, *args, PAGE, (page - 1) * PAGE)
    claims = await ctx.db.fetch(CLAIMS_OF, ctx.guild.id, [int(r["id"]) for r in rows])
    by_ticket: dict[int, list[ClaimShown]] = {}
    for c in claims:
        by_ticket.setdefault(int(c["ticket_id"]), []).append(
            ClaimShown(id=c["id"], member=c["member"], note=c["note"], state=c["state"], reason=c["reason"])
        )
    return TicketPage(
        tickets=[
            TicketShown(
                id=r["id"],
                title=r["title"],
                body=r["body"],
                key=r["key"],
                state=r["state"],
                resolution=r["resolution"],
                updated_at=r["updated_at"],
                claims=by_ticket.get(int(r["id"]), []),
            )
            for r in rows
        ],
        page=page,
        pages=max(1, -(-total // PAGE)),
    )


KEEP = timedelta(days=90)


@plugin.job(every=timedelta(days=1))
async def clean_up(ctx: Ctx) -> None:
    """Delete cancelled tickets and every claim not accepted, 90 days after they closed or were settled. Accepted
    tickets stay while their queue does, since programs reconcile against them."""
    cutoff = ctx.now - KEEP
    await ctx.db.execute(
        "DELETE FROM claims WHERE guild_id = $1 AND state IN ('rejected', 'withdrawn', 'revoked') AND settled_at < $2",
        ctx.guild.id,
        cutoff,
    )
    await ctx.db.execute(
        "DELETE FROM tickets WHERE guild_id = $1 AND resolution = 'cancelled' AND closed_at < $2",
        ctx.guild.id,
        cutoff,
    )
