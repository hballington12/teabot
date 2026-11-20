"""Plugin events: a plugin declares what it emits, emits inside its transaction, and each subscriber hears each
event as a job of its own, carrying the event's ID; deleting a member's data deletes the events naming them."""

from typing import Any

import discord
import pytest
from pydantic import BaseModel

from teabot.core.loader import Loaded, event_problems
from teabot.core.member_data import delete_member_data
from teabot.core.registry import Call
from teabot.sdk import Actor, Context, EmptyConfig, MemberRef, Plugin, UntrustedText
from teabot.sdk._signature import SignatureError
from teabot.sdk.events import Event, Received, paths
from teabot.testing import HarnessFactory, PluginHarness


class Accepted(BaseModel):
    ticket: int
    title: UntrustedText
    claimant: MemberRef


class Unknown(BaseModel):
    ticket: int


class Many(BaseModel):
    n: int


plugin = Plugin(
    "desk",
    emits=[
        Event("accepted", Accepted, "A claim on a ticket was accepted"),
        Event("many", Many, "One of many"),
    ],
)
type Ctx = Context[EmptyConfig]
heard: list[Received[Accepted]] = []
failing: list[bool] = []


@plugin.action()
async def accept(ctx: Ctx, ticket: int, claimant: int) -> str:
    """Accept a claim.

    Args:
        ticket: The ticket
        claimant: Whose claim
    """
    async with ctx.db.transaction() as tx:
        await tx.emit(Accepted(ticket=ticket, title=f"Ticket {ticket}", claimant=claimant))
    return "accepted"


@plugin.action()
async def stray(ctx: Ctx) -> str:
    """Emit an undeclared event."""
    async with ctx.db.transaction() as tx:
        await tx.emit(Unknown(ticket=1))
    return ""


@plugin.action()
async def flood(ctx: Ctx, count: int) -> str:
    """Emit many events in one transaction.

    Args:
        count: How many
    """
    async with ctx.db.transaction() as tx:
        for n in range(count):
            await tx.emit(Many(n=n))
    return ""


@plugin.on_event("desk.accepted", Accepted)
async def on_accepted(ctx: Ctx, event: Received[Accepted]) -> None:
    if failing:
        raise RuntimeError("the subscriber is down")
    heard.append(event)


async def setup(teabot_harness: HarnessFactory) -> PluginHarness:
    heard.clear()
    failing.clear()
    return await teabot_harness(plugin)


async def test_a_subscriber_hears_an_event_with_its_typed_payload_and_who_caused_it(
    teabot_harness: HarnessFactory,
) -> None:
    harness = await setup(teabot_harness)
    claimant = harness.guild.add_member(discord.Permissions.none(), name="sam")
    await harness.call(accept, ticket=7, claimant=claimant.id)
    await harness.run_jobs()
    [event] = heard
    assert (event.source, event.name, event.data.ticket, event.data.claimant) == (
        "desk",
        "accepted",
        7,
        claimant.id,
    )
    assert event.by == harness.member.id
    db: Any = harness.admin
    row = await db.fetchrow("SELECT member_ids, untrusted FROM core.events WHERE id = $1", event.id)
    assert (list(row["member_ids"]), list(row["untrusted"])) == ([claimant.id], ["title"])


async def test_an_event_gone_before_its_subscriber_ran_is_skipped(teabot_harness: HarnessFactory) -> None:
    harness = await setup(teabot_harness)
    await harness.call(accept, ticket=1, claimant=harness.member.id)
    db: Any = harness.admin
    # The delivery runs, then the event goes, as after 30 days.
    await harness.run_jobs()
    heard.clear()
    await db.execute("UPDATE core.jobs SET state = 'pending' WHERE handler = 'on_event:desk.accepted'")
    await db.execute("DELETE FROM core.events")
    await harness.run_jobs()
    assert heard == []


async def test_a_subscriber_that_keeps_failing_tells_the_log(teabot_harness: HarnessFactory) -> None:
    harness = await setup(teabot_harness)
    failing.append(True)
    await harness.call(accept, ticket=1, claimant=harness.member.id)
    db: Any = harness.admin
    await harness.run_jobs(raise_failures=False)
    attempts = await db.fetchval(
        "SELECT max_attempts FROM core.jobs WHERE handler = 'on_event:desk.accepted'"
    )
    assert attempts == 13
    await db.execute(
        "UPDATE core.jobs SET attempts = max_attempts - 1, run_at = now(), state = 'pending' "
        "WHERE handler = 'on_event:desk.accepted'"
    )
    await harness.run_jobs(raise_failures=False)
    lost = await db.fetchval("SELECT input FROM core.audit_log WHERE action = 'events.lost'")
    assert '"event": "desk.accepted"' in lost


async def test_emitting_refuses_an_undeclared_model_and_too_many_events(
    teabot_harness: HarnessFactory,
) -> None:
    harness = await setup(teabot_harness)
    with pytest.raises(Exception, match="doesn't declare"):
        await harness.call(stray)
    with pytest.raises(Exception, match="at most 100 events"):
        await harness.call(flood, count=101)
    db: Any = harness.admin
    assert await db.fetchval("SELECT count(*) FROM core.events") == 0


async def test_deleting_a_member_deletes_the_events_naming_them(teabot_harness: HarnessFactory) -> None:
    harness = await setup(teabot_harness)
    sam = harness.guild.add_member(discord.Permissions.none(), name="sam")
    await harness.call(accept, ticket=1, claimant=sam.id)
    await harness.call(accept, ticket=2, claimant=harness.member.id)
    db: Any = harness.admin
    await delete_member_data(db, harness.pools.naming, sam.id)
    assert [r["payload"] for r in await db.fetch("SELECT payload FROM core.events")] != []
    assert await db.fetchval("SELECT count(*) FROM core.events WHERE $1 = ANY(member_ids)", sam.id) == 0
    await delete_member_data(db, harness.pools.naming, harness.member.id)
    assert await db.fetchval("SELECT count(*) FROM core.events") == 0


def test_a_payload_holds_plain_fields_and_finds_members_and_untrusted_text() -> None:
    class Item(BaseModel):
        who: MemberRef
        note: UntrustedText | None = None

    class Batch(BaseModel):
        items: list[Item]
        by_hand: bool

    found = paths(Batch)
    assert (found.members, found.untrusted) == (("items[].who",), ("items[].note",))

    class Bad(BaseModel):
        data: dict[str, int]

    with pytest.raises(SignatureError, match="not a payload type"):
        Event("bad", Bad, "Refused")


def test_two_events_may_not_share_a_model() -> None:
    with pytest.raises(SignatureError, match="share the model"):
        Plugin("twin", emits=[Event("one", Many, "One"), Event("two", Many, "Two")])


def test_loading_names_a_subscription_nobody_emits_and_a_field_the_emitter_lacks() -> None:
    class Wants(BaseModel):
        ticket: int
        queue: str

    listener = Plugin("listener")

    @listener.on_event("desk.accepted", Wants)
    async def wants(ctx: Context[EmptyConfig], event: Received[Wants]) -> None: ...

    @listener.on_event("nobody.home", Wants)
    async def lonely(ctx: Context[EmptyConfig], event: Received[Wants]) -> None: ...

    problems = event_problems({"desk": Loaded(plugin), "listener": Loaded(listener)})
    assert problems == [
        "listener needs queue in desk.accepted, which its payload doesn't have",
        "listener subscribes to nobody.home, which no loaded plugin declares",
    ]


async def feed(harness: PluginHarness, after: str = "", names: list[str] | None = None) -> Any:
    actor = Actor(harness.member.id, "service", None)  # pyright: ignore[reportArgumentType]
    raw: dict[str, Any] = {"after": after, "names": names or []}
    return await harness.registry.invoke(Call("admin.events", harness.guild.id, actor, raw))


async def test_the_feed_pages_events_by_cursor_and_marks_member_text(teabot_harness: HarnessFactory) -> None:
    harness = await setup(teabot_harness)
    harness.member.guild_permissions = discord.Permissions(manage_guild=True)
    await harness.call(accept, ticket=1, claimant=harness.member.id)
    await harness.call(accept, ticket=2, claimant=harness.member.id)
    first = await feed(harness)
    assert [e.data["ticket"] for e in first.events] == [1, 2]
    assert first.events[0].data["title"] == {"untrusted_text": "Ticket 1"}
    assert first.events[0].by == str(harness.member.id)
    await harness.call(flood, count=2)
    later = await feed(harness, first.cursor)
    assert [(e.name, e.data["n"]) for e in later.events] == [("many", 0), ("many", 1)]
    assert (await feed(harness, later.cursor)).events == []
    only = await feed(harness, names=["desk.accepted"])
    assert len(only.events) == 2


async def test_the_feed_needs_manage_server(teabot_harness: HarnessFactory) -> None:
    harness = await setup(teabot_harness)
    harness.member.guild_permissions = discord.Permissions.none()
    with pytest.raises(Exception, match="permissions"):
        await feed(harness)
