"""The member directory (D55): the writer's diff and history, explanations from Discord's audit log, the reconcile and
its guard, the join-method lookup, retention, and the gateway's parser table."""

import json
from collections.abc import AsyncIterator, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import discord
import pytest

from teabot.core.directory.gateway import PARSERS
from teabot.core.directory.inbox import AuditEntry, Banned, Entry, Joined, Left, RoleDeleted, Updated
from teabot.core.directory.reconcile import DirectorySettings
from teabot.core.directory.rows import MemberRow
from teabot.core.directory.service import Directory, ensure_partitions
from teabot.core.directory.writer import Writer
from teabot.core.events import Events
from teabot.core.queue import Queue
from teabot.core.worker import Workers
from teabot.db.migrate import migrate
from teabot.db.naming import Naming
from teabot.db.pool import Pools
from teabot.db.types import Conn
from teabot.sdk.plugin import EventName

GUILD = 1 << 22
BOT = 999
KICK, BAN, ROLE_UPDATE = 20, 22, 25


def payload(
    user_id: int,
    *,
    roles: tuple[int, ...] = (),
    nick: str | None = None,
    joined: str = "2026-01-01T00:00:00+00:00",
) -> dict[str, Any]:
    return {
        "guild_id": str(GUILD),
        "user": {"id": str(user_id), "username": f"user{user_id}", "global_name": None},
        "nick": nick,
        "roles": [str(r) for r in roles],
        "joined_at": joined,
    }


def row(user_id: int, **kwargs: Any) -> MemberRow:
    return MemberRow.from_payload(payload(user_id, **kwargs))


def now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Facts:
    member_count: int | None
    role_ids: frozenset[int]


@dataclass
class FakeApi:
    """Discord's member list and search for one server."""

    listed: dict[int, dict[str, Any]] = field(default_factory=dict[int, dict[str, Any]])
    member_count: int | None = None
    roles: frozenset[int] = frozenset({1, 2, 3})
    searched: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    bodies: list[Mapping[str, Any]] = field(default_factory=list[Mapping[str, Any]])

    def shard_count(self) -> int:
        return 1

    def bot_id(self) -> int | None:
        return BOT

    def facts(self, guild_id: int) -> Facts | None:
        count = len(self.listed) if self.member_count is None else self.member_count
        return Facts(count, self.roles) if guild_id == GUILD else None

    async def list_members(self, guild_id: int, after: int) -> list[Mapping[str, Any]]:
        listed: list[Mapping[str, Any]] = [self.listed[k] for k in sorted(self.listed) if k > after]
        return listed[:1000]

    async def search_members(self, guild_id: int, body: Mapping[str, Any]) -> Any:
        self.bodies.append(dict(body))
        return {"members": self.searched}


@dataclass
class Setup:
    directory: Directory
    api: FakeApi
    admin: Conn
    queue: Queue

    async def send(self, *entries: Entry) -> None:
        for entry in entries:
            self.directory.offer(entry)
        await self.directory.writer(0).queue.join()

    async def member(self, user_id: int) -> Any:
        return await self.admin.fetchrow(
            "SELECT * FROM core.members WHERE guild_id = $1 AND user_id = $2", GUILD, user_id
        )

    async def history(self) -> list[Any]:
        return await self.admin.fetch(
            "SELECT user_id, kind, source, since, actor_id, reason, detail FROM core.member_events ORDER BY at, kind"
        )

    async def jobs(self) -> list[tuple[str, str, dict[str, Any]]]:
        rows = await self.admin.fetch(
            "SELECT plugin_id, handler, payload FROM core.jobs WHERE plugin_id <> 'core' ORDER BY id"
        )
        return [(r["plugin_id"], r["handler"], json.loads(r["payload"])) for r in rows]

    async def reconcile(self) -> None:
        await self.directory.reconciler.request(GUILD, "session")
        assert await Workers(self.queue, lambda: ["core"]).run_once()


@pytest.fixture
async def setup(admin: Conn, naming: Naming, pools: Pools) -> AsyncIterator[Setup]:
    await migrate(admin, naming, [])
    db = pools.core_db()
    await ensure_partitions(db)
    queue = Queue(db)
    listeners: dict[str, frozenset[EventName]] = {
        "greeter": frozenset({"member_join", "member_leave", "member_roles"})
    }
    late: dict[str, frozenset[EventName]] = {"latecomer": frozenset({"member_join"})}
    events = Events(db, queue, listeners, late=late)
    await admin.execute("INSERT INTO core.guilds (guild_id) VALUES ($1)", GUILD)
    for plugin in ("greeter", "latecomer"):
        await admin.execute(
            "INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled) VALUES ($1, $2, true)",
            GUILD,
            plugin,
        )
    api = FakeApi()
    directory = Directory(db, queue, events, api, DirectorySettings())
    yield Setup(directory, api, admin, queue)
    await directory.close()


async def test_a_join_writes_the_row_its_history_and_the_plugins_event(setup: Setup) -> None:
    await setup.send(Joined(GUILD, row(10, roles=(1,)), now()))
    member = await setup.member(10)
    assert member["role_ids"] == [1] and member["left_at"] is None
    [joined] = await setup.history()
    assert (joined["kind"], joined["source"]) == ("joined", "event")
    assert await setup.jobs() == [("greeter", "on_member_join", {"user_id": 10})]


async def test_an_update_records_roles_and_nickname_and_tells_plugins_of_roles(setup: Setup) -> None:
    await setup.send(
        Joined(GUILD, row(10, roles=(1,)), now()), Updated(GUILD, row(10, roles=(2,), nick="Tea"), now())
    )
    kinds = {r["kind"]: json.loads(r["detail"]) for r in await setup.history()}
    assert kinds["roles"] == {"added": ["2"], "removed": ["1"]}
    assert kinds["nickname"] == {"old": None, "new": "Tea"}
    assert ("greeter", "on_member_roles", {"user_id": 10, "added": [2], "removed": [1]}) in await setup.jobs()


async def test_an_update_for_a_member_with_no_row_and_no_cached_copy_writes_the_row_alone(
    setup: Setup,
) -> None:
    await setup.send(Updated(GUILD, row(11, roles=(1,)), now()))
    assert (await setup.member(11))["role_ids"] == [1]
    assert await setup.history() == []
    assert await setup.jobs() == []


async def test_a_cached_copy_says_what_changed_for_a_member_with_no_row(setup: Setup) -> None:
    await setup.send(Updated(GUILD, row(11, roles=(1, 2)), now(), cached_roles=(1,)))
    [roles] = await setup.history()
    assert json.loads(roles["detail"]) == {"added": ["2"], "removed": []}
    assert await setup.jobs() == [
        ("greeter", "on_member_roles", {"user_id": 11, "added": [2], "removed": []})
    ]


async def test_a_kick_found_after_the_leave_turns_it_into_a_kick(setup: Setup) -> None:
    await setup.send(Joined(GUILD, row(10), now()), Left(GUILD, 10, "user10", now()))
    await setup.send(AuditEntry(GUILD, KICK, 10, 5, "spam", (), now()))
    left = [r for r in await setup.history() if r["kind"] != "joined"]
    assert [(r["kind"], r["actor_id"], r["reason"]) for r in left] == [("kicked", 5, "spam")]


async def test_a_kick_heard_before_the_leave_waits_for_it(setup: Setup) -> None:
    await setup.send(Joined(GUILD, row(10), now()), AuditEntry(GUILD, KICK, 10, 5, None, (), now()))
    await setup.send(Left(GUILD, 10, "user10", now()))
    assert [r["kind"] for r in await setup.history()] == ["joined", "kicked"]


async def test_a_ban_event_then_its_audit_entry_name_the_ban_and_who(setup: Setup) -> None:
    await setup.send(
        Joined(GUILD, row(10), now()), Banned(GUILD, 10, now()), Left(GUILD, 10, "user10", now())
    )
    await setup.send(AuditEntry(GUILD, BAN, 10, 5, "raid", (), now()))
    last = (await setup.history())[-1]
    assert (last["kind"], last["actor_id"], last["reason"]) == ("banned", 5, "raid")


async def test_a_role_change_teabot_made_names_the_member_who_asked(setup: Setup) -> None:
    await setup.send(Joined(GUILD, row(10), now()), Updated(GUILD, row(10, roles=(1,)), now()))
    reason = "via teabot: roles.bulk_give, for member 42"
    await setup.send(AuditEntry(GUILD, ROLE_UPDATE, 10, BOT, reason, ({"key": "$add"},), now()))
    roles = [r for r in await setup.history() if r["kind"] == "roles"]
    assert roles[0]["actor_id"] == 42


async def test_a_deleted_role_leaves_every_row_and_remembers_its_holders(setup: Setup) -> None:
    await setup.send(Joined(GUILD, row(10, roles=(1, 2)), now()), Joined(GUILD, row(11, roles=(2,)), now()))
    await setup.send(RoleDeleted(GUILD, 2, "Raiders", now()))
    assert (await setup.member(10))["role_ids"] == [1]
    deleted = (await setup.history())[-1]
    assert deleted["kind"] == "role_deleted" and deleted["user_id"] is None
    assert json.loads(deleted["detail"]) == {"role_id": "2", "name": "Raiders", "holders": ["10", "11"]}


async def test_the_backfill_writes_rows_with_no_history_and_tells_plugins_nothing(setup: Setup) -> None:
    setup.api.listed = {u: payload(u) for u in (10, 11, 12)}
    await setup.reconcile()
    assert await setup.admin.fetchval("SELECT count(*) FROM core.members") == 3
    assert await setup.history() == []
    assert await setup.jobs() == []
    state = await setup.admin.fetchrow("SELECT * FROM core.directory_state WHERE guild_id = $1", GUILD)
    assert state is not None
    assert state["backfilled"] and state["history_from"] is not None and not state["guard_stopped"]


async def backfilled(setup: Setup, *users: int) -> None:
    setup.api.listed = {u: payload(u) for u in users}
    await setup.reconcile()
    # Rows the backfill wrote are older than the next reconcile's margin.
    await setup.admin.execute("UPDATE core.members SET observed_at = observed_at - interval '5 minutes'")
    await setup.admin.execute("UPDATE core.directory_state SET reconciled_at = now() - interval '2 hours'")


async def test_a_reconcile_records_what_changed_in_the_gap_as_late_events(setup: Setup) -> None:
    await backfilled(setup, 10, 11, 12)
    setup.api.listed = {10: payload(10), 12: payload(12, roles=(1,)), 13: payload(13)}
    await setup.reconcile()
    found = {(r["user_id"], r["kind"]) for r in await setup.history()}
    assert found == {(11, "left"), (12, "roles"), (13, "joined")}
    assert all(r["source"] == "reconcile" and r["since"] is not None for r in await setup.history())
    assert (await setup.member(11))["left_at"] is not None
    jobs = await setup.jobs()
    assert [(p, h) for p, h, _ in jobs] == [("latecomer", "on_member_join")]
    assert jobs[0][2]["user_id"] == 13 and "since" in jobs[0][2]


async def test_a_rejoin_in_the_gap_is_a_leave_and_a_join(setup: Setup) -> None:
    await backfilled(setup, 10)
    setup.api.listed = {10: payload(10, joined="2026-06-01T00:00:00+00:00")}
    await setup.reconcile()
    assert [r["kind"] for r in await setup.history()] == ["joined", "left"]


async def test_the_guard_marks_no_one_left_when_the_listing_falls_short(setup: Setup) -> None:
    await backfilled(setup, *range(10, 20))
    setup.api.listed = {u: payload(u) for u in range(10, 13)}
    setup.api.member_count = 1000
    await setup.reconcile()
    assert await setup.admin.fetchval("SELECT count(*) FROM core.members WHERE left_at IS NOT NULL") == 0
    assert await setup.admin.fetchval("SELECT guard_stopped FROM core.directory_state")


async def test_a_page_never_undoes_a_newer_event(setup: Setup) -> None:
    await backfilled(setup, 10)
    await setup.send(Updated(GUILD, row(10, roles=(1,)), now()))
    setup.api.listed = {10: payload(10)}
    await setup.reconcile()
    assert (await setup.member(10))["role_ids"] == [1]


async def test_the_lookup_reads_join_methods(setup: Setup) -> None:
    setup.api.searched = [
        {"member": payload(10), "join_source_type": 5, "source_invite_code": "tea", "inviter_id": "7"},
    ]
    await backfilled(setup, 10)
    member = await setup.member(10)
    assert (member["join_source"], member["source_invite_code"], member["inviter_id"]) == (5, "tea", 7)


async def test_retention_forgets_members_who_left_long_ago(setup: Setup) -> None:
    await setup.send(
        Joined(GUILD, row(10), now()), Left(GUILD, 10, "user10", now()), Joined(GUILD, row(11), now())
    )
    await setup.admin.execute(
        "UPDATE core.members SET left_at = now() - interval '400 days' WHERE user_id = 10"
    )
    await setup.directory.upkeep(now().date())
    assert [r["user_id"] for r in await setup.admin.fetch("SELECT user_id FROM core.members")] == [11]


async def test_a_failed_entry_is_skipped_and_the_rest_of_its_batch_applied(
    setup: Setup, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = setup.directory.writer(0)
    original = writer.apply.one

    async def failing(tx: Any, entry: Entry) -> None:
        if isinstance(entry, Joined) and entry.member.user_id == 11:
            raise RuntimeError("bad event")
        await original(tx, entry)

    monkeypatch.setattr(writer.apply, "one", failing)
    await setup.send(*(Joined(GUILD, row(u), now()) for u in (10, 11, 12)))
    users = [r["user_id"] for r in await setup.admin.fetch("SELECT user_id FROM core.members ORDER BY 1")]
    assert users == [10, 12]


async def test_discord_py_still_has_the_parsers_the_directory_wraps() -> None:
    """A discord.py release that renames or moves them fails here first (D55)."""
    client = discord.Client(intents=discord.Intents.default())
    assert set(PARSERS) <= set(client._connection.parsers)  # pyright: ignore[reportPrivateUsage]
    await client.close()


async def test_a_wrapped_parser_offers_the_event_and_runs_the_original(setup: Setup) -> None:
    ran: list[Any] = []
    parsers = {name: ran.append for name in PARSERS}
    assert setup.directory.listen(parsers, lambda _guild_id: None)
    parsers["GUILD_MEMBER_ADD"](payload(10))
    await setup.directory.writer(0).queue.join()
    assert ran == [payload(10)]
    assert (await setup.member(10)) is not None


async def test_the_directory_does_not_listen_when_a_parser_is_missing(setup: Setup) -> None:
    def ignore(_data: Any) -> None:
        return None

    parsers: dict[str, Callable[[Any], Any]] = {
        name: ignore for name in PARSERS if name != "GUILD_MEMBER_UPDATE"
    }
    assert not setup.directory.listen(parsers, lambda _guild_id: None)
    assert "GUILD_MEMBER_ADD" in parsers and not setup.directory.listening


async def test_a_full_queue_drops_gateway_events_and_reconciles_the_shard_once_it_commits(
    setup: Setup,
) -> None:
    await backfilled(setup, 10)
    await setup.directory.close()
    old = setup.directory.writers.pop(0)
    writer = Writer(0, old.db, old.apply, limit=1, on_dropped=old.on_dropped)
    setup.directory.writers[0] = writer
    writer.offer(Joined(GUILD, row(11), now()))
    writer.offer(Joined(GUILD, row(12), now()))
    assert writer.dropped == 1
    writer.start()
    await writer.queue.join()
    assert writer.dropped == 0
    assert await setup.admin.fetchval("SELECT dropped FROM core.directory_state")
    reason = await setup.admin.fetchval(
        "SELECT payload->>'reason' FROM core.jobs WHERE handler = 'directory_reconcile' AND state = 'pending'"
    )
    assert reason == "dropped"
