"""The member directory's tools (D55): filters, counts, history, the directory's state on every answer, and
`admin.find_members` answering from the directory once it is ready."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from teabot.builtin.lookups import FindMembers, Lookups
from teabot.builtin.members import HistoryQuery, Members, MembersQuery
from teabot.db.migrate import migrate
from teabot.db.naming import Naming
from teabot.db.pool import Pools
from teabot.db.types import Conn
from teabot.sdk import ActionError

GUILD = 5 << 22
OLD_ACCOUNT = 100 << 22
NEW_ACCOUNT = (1_700_000_000_000 - 1420070400000) << 22


class Guild:
    id = GUILD
    member_count = 4

    def get_role(self, role_id: int) -> Any:
        return SimpleNamespace(name={1: "Raiders", 2: "Staff"}.get(role_id, "role"))

    async def query_members(self, query: str, *, limit: int) -> list[Any]:
        return [SimpleNamespace(id=1, name="from-discord", display_name="from-discord")]


def ctx() -> Any:
    return SimpleNamespace(guild=Guild())


async def add(admin: Conn, user_id: int, name: str, **columns: Any) -> None:
    values: dict[str, Any] = {"role_ids": [], "joined_at": datetime(2026, 3, 1, tzinfo=UTC), **columns}
    names = ", ".join(values)
    marks = ", ".join(f"${i + 4}" for i in range(len(values)))
    await admin.execute(
        f"INSERT INTO core.members (guild_id, user_id, name, observed_at, {names}) VALUES ($1, $2, $3, now(), {marks})",
        GUILD,
        user_id,
        name,
        *values.values(),
    )


@pytest.fixture
async def members(admin: Conn, naming: Naming, pools: Pools) -> Members:
    await migrate(admin, naming, [])
    await admin.execute(
        "INSERT INTO core.directory_state (guild_id, backfilled, history_from) VALUES ($1, true, now())",
        GUILD,
    )
    await add(
        admin, OLD_ACCOUNT, "alice", role_ids=[1], nickname="Al", join_source=5, source_invite_code="tea"
    )
    await add(admin, NEW_ACCOUNT, "bob", role_ids=[1, 2], joined_at=datetime(2026, 6, 1, tzinfo=UTC))
    await add(admin, NEW_ACCOUNT + 1, "carol")
    await add(admin, NEW_ACCOUNT + 2, "dave", left_at=datetime(2026, 7, 1, tzinfo=UTC))
    return Members(pools.core_db())


async def test_members_filters_by_roles_and_says_how_far_to_trust_it(members: Members) -> None:
    page = await members.members(ctx(), MembersQuery(roles_any=[1]))
    assert sorted(m.name for m in page.members) == ["alice", "bob"]
    assert page.total == 2 and page.directory.ready
    page = await members.members(ctx(), MembersQuery(roles_all=[1, 2]))
    assert [m.name for m in page.members] == ["bob"]
    page = await members.members(ctx(), MembersQuery(no_roles=True))
    assert [m.name for m in page.members] == ["carol"]


async def test_members_who_left_are_kept_apart(members: Members) -> None:
    page = await members.members(ctx(), MembersQuery(status="left"))
    assert [m.name for m in page.members] == ["dave"]
    assert (await members.members(ctx(), MembersQuery(status="everyone"))).total == 4


async def test_members_filters_by_dates_account_age_join_method_and_name(members: Members) -> None:
    page = await members.members(ctx(), MembersQuery(joined_after="2026-05-01"))
    assert [m.name for m in page.members] == ["bob"]
    page = await members.members(ctx(), MembersQuery(created_before="2020-01-01"))
    assert [m.name for m in page.members] == ["alice"]
    page = await members.members(ctx(), MembersQuery(join_method=["invite"], invite_code="tea"))
    assert [(m.name, m.join_method) for m in page.members] == [("alice", "invite")]
    page = await members.members(ctx(), MembersQuery(name="AL"))
    assert [m.name for m in page.members] == ["alice"]


async def test_a_name_with_like_characters_matches_them_literally(members: Members) -> None:
    assert (await members.members(ctx(), MembersQuery(name="%"))).total == 0


async def test_members_counts_by_role(members: Members) -> None:
    page = await members.members(ctx(), MembersQuery(group_by="role"))
    assert page.groups is not None
    assert {(g.key, g.label, g.count) for g in page.groups} == {
        ("1", "Raiders", 2),
        ("2", "Staff", 1),
        ("0", None, 1),
    }
    assert page.members == []


async def test_a_join_method_filter_reads_new_joins_first(members: Members) -> None:
    asked: list[int] = []

    async def lookup(guild_id: int) -> None:
        asked.append(guild_id)

    members.lookup_joins = lookup
    await members.members(ctx(), MembersQuery(join_method=["invite"]))
    await members.members(ctx(), MembersQuery(roles_any=[1]))
    assert asked == [GUILD]


async def test_history_lists_a_members_events_newest_first(members: Members, admin: Conn) -> None:
    for kind, detail, at in (
        ("joined", {"join_source": 5}, datetime(2026, 3, 1, tzinfo=UTC)),
        ("roles", {"added": ["1"], "removed": []}, datetime(2026, 3, 2, tzinfo=UTC)),
    ):
        await admin.execute(
            "INSERT INTO core.member_events (guild_id, user_id, kind, at, source, detail) "
            "VALUES ($1, $2, $3, $4, 'event', $5::jsonb)",
            GUILD,
            OLD_ACCOUNT,
            kind,
            at,
            json.dumps(detail),
        )
    page = await members.member_history(ctx(), HistoryQuery(member=OLD_ACCOUNT))
    assert [(e.kind, e.roles_added, e.join_method) for e in page.events] == [
        ("roles", [1], None),
        ("joined", [], "invite"),
    ]
    only = await members.member_history(ctx(), HistoryQuery(kinds=["joined"]))
    assert only.total == 1


async def test_before_the_backfill_the_tools_say_so(members: Members, admin: Conn) -> None:
    await admin.execute("UPDATE core.directory_state SET backfilled = false")
    with pytest.raises(ActionError, match="still filling: 3 of 4"):
        await members.members(ctx(), MembersQuery())


async def test_find_members_answers_from_the_directory_once_ready(
    members: Members, admin: Conn, pools: Pools
) -> None:
    lookups = Lookups(pools.core_db())
    found = await lookups.find_members(ctx(), FindMembers(query="a"))
    assert [(m.name, m.display_name) for m in found.members] == [("alice", "Al")]
    await admin.execute("UPDATE core.directory_state SET backfilled = false")
    found = await lookups.find_members(ctx(), FindMembers(query="a"))
    assert [m.name for m in found.members] == ["from-discord"]
