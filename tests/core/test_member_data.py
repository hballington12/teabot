"""Deleting a member's data finds their rows in every plugin by type, and anonymises the core's records."""

from pathlib import Path

import discord
import pytest

from teabot.core.member_data import delete_member_data
from teabot.db.migrate import migrate, schema_problems
from teabot.db.naming import Naming
from teabot.db.pool import Pools
from teabot.db.types import Conn
from teabot.sdk import Context, EmptyConfig, Plugin
from teabot.testing import HarnessFactory, PluginHarness
from teabot.testing.fakes import FakeMember

raffle = Plugin("raffle", migrations=Path(__file__).parent / "member_data_migrations")
type Ctx = Context[EmptyConfig]


@raffle.action()
async def enter(ctx: Ctx) -> str:
    """Enter the raffle."""
    await ctx.db.execute("INSERT INTO entries (member_id) VALUES ($1)", ctx.actor.user_id)
    return "in"


@pytest.fixture
async def harness(teabot_harness: HarnessFactory) -> PluginHarness:
    return await teabot_harness(raffle)


async def entrants(harness: PluginHarness) -> list[int]:
    rows = await harness.admin.fetch("SELECT member_id FROM plugin_raffle.entries ORDER BY member_id")
    return [int(r["member_id"]) for r in rows]


async def entered(harness: PluginHarness, count: int) -> list[FakeMember]:
    members = [harness.guild.add_member(discord.Permissions.none()) for _ in range(count)]
    for member in members:
        await harness.as_member(member).call(enter)
    return members


async def test_a_members_entries_are_deleted_and_the_audit_log_kept_without_them(
    harness: PluginHarness,
) -> None:
    gone, stays = await entered(harness, 2)
    deleted = await delete_member_data(harness.admin, harness.pools.naming, gone.id)
    assert deleted.plugins == {"raffle.entries": 1}
    assert deleted.core["audit log"] >= 1
    assert await entrants(harness) == [stays.id]
    assert not await harness.admin.fetchval("SELECT count(*) FROM core.audit_log WHERE user_id = $1", gone.id)
    again = await delete_member_data(harness.admin, harness.pools.naming, gone.id)
    assert again.total == 0


async def test_with_a_server_only_that_server_is_touched(harness: PluginHarness) -> None:
    (member,) = await entered(harness, 1)
    elsewhere = await delete_member_data(harness.admin, harness.pools.naming, member.id, harness.guild.id + 1)
    assert elsewhere.total == 0
    assert await entrants(harness) == [member.id]


async def test_a_bigint_member_column_is_a_problem_naming_the_type_to_use(harness: PluginHarness) -> None:
    await harness.admin.execute(
        "CREATE TABLE plugin_raffle.notes (guild_id bigint NOT NULL, author_member_id bigint, winner_ids bigint[])"
    )
    problems = await schema_problems(harness.admin, "plugin_raffle")
    assert any("notes.author_member_id" in p and "type teabot.member_id" in p for p in problems)
    assert any("notes.winner_ids" in p and "teabot.member_id[]" in p for p in problems)


async def test_a_member_actor_column_is_emptied_and_its_row_kept(harness: PluginHarness) -> None:
    gone, stays = await entered(harness, 2)
    await harness.admin.execute(
        "CREATE TABLE plugin_raffle.draws "
        "(guild_id bigint NOT NULL, winner teabot.member_id, drawn_by teabot.member_actor)"
    )
    owner = harness.pools.naming.plugin_role("raffle")
    await harness.admin.execute(f'GRANT ALL ON plugin_raffle.draws TO "{owner}"')
    await harness.admin.execute(
        "INSERT INTO plugin_raffle.draws VALUES ($1, $2, $3)", harness.guild.id, stays.id, gone.id
    )
    deleted = await delete_member_data(harness.admin, harness.pools.naming, gone.id)
    assert deleted.plugins == {"raffle.entries": 1, "raffle.draws": 1}
    row = await harness.admin.fetchrow("SELECT winner, drawn_by FROM plugin_raffle.draws")
    assert row is not None
    assert (row["winner"], row["drawn_by"]) == (stays.id, None)


async def test_a_member_actor_column_may_not_be_required(harness: PluginHarness) -> None:
    await harness.admin.execute(
        "CREATE TABLE plugin_raffle.draws (guild_id bigint NOT NULL, drawn_by teabot.member_actor NOT NULL)"
    )
    problems = await schema_problems(harness.admin, "plugin_raffle")
    assert any("draws.drawn_by" in p and "let it be null" in p for p in problems)


async def test_the_member_directory_forgets_the_member_and_whom_they_invited_or_removed(
    admin: Conn, naming: Naming, pools: Pools
) -> None:
    await migrate(admin, naming, [])
    for user_id, inviter in ((7, None), (8, 7)):
        await admin.execute(
            "INSERT INTO core.members (guild_id, user_id, name, inviter_id, observed_at) "
            "VALUES (1, $1, 'x', $2, now())",
            user_id,
            inviter,
        )
    await admin.execute(
        "INSERT INTO core.member_events (guild_id, user_id, kind, at, source, actor_id, detail) VALUES "
        "(1, 7, 'joined', now(), 'event', NULL, '{}'), (1, 8, 'kicked', now(), 'event', 7, '{}'), "
        """(1, 8, 'joined', now(), 'event', NULL, '{"inviter_id": "7"}'), """
        """(1, NULL, 'role_deleted', now(), 'event', NULL, '{"holders": ["7", "8"]}')"""
    )
    deleted = await delete_member_data(admin, naming, 7)
    assert deleted.core["member directory"] == 1 and deleted.core["member history"] == 1
    assert await admin.fetchval("SELECT inviter_id FROM core.members WHERE user_id = 8") == 0
    assert await admin.fetchval("SELECT actor_id FROM core.member_events WHERE kind = 'kicked'") == 0
    details = [
        r["detail"] for r in await admin.fetch("SELECT detail::text FROM core.member_events ORDER BY kind")
    ]
    assert all('"7"' not in d for d in details)
