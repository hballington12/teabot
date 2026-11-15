"""Deleting a member's data finds their rows in every plugin by type, and anonymises the core's records."""

import discord
import pytest

from teabot.core.member_data import delete_member_data
from teabot.db.migrate import schema_problems
from teabot.plugins.giveaways import enter, start
from teabot.plugins.giveaways import plugin as giveaways
from teabot.testing import HarnessFactory, PluginHarness
from teabot.testing.fakes import FakeChannel, FakeMember


@pytest.fixture
async def harness(teabot_harness: HarnessFactory) -> PluginHarness:
    return await teabot_harness(giveaways)


async def entrants(harness: PluginHarness) -> list[int]:
    rows = await harness.admin.fetch("SELECT member_id FROM plugin_giveaways.entries ORDER BY member_id")
    return [int(r["member_id"]) for r in rows]


async def entered(harness: PluginHarness, count: int) -> list[FakeMember]:
    news = harness.guild.add_channel(FakeChannel(name="news"))
    out = await harness.call(start, channel=news, prize="Nitro")
    members = [harness.guild.add_member(discord.Permissions.none()) for _ in range(count)]
    for member in members:
        await harness.as_member(member).call(enter, giveaway=out.giveaway)
    return members


async def test_a_members_entries_are_deleted_and_the_audit_log_kept_without_them(
    harness: PluginHarness,
) -> None:
    gone, stays = await entered(harness, 2)
    deleted = await delete_member_data(harness.admin, harness.pools.naming, gone.id)
    assert deleted.plugins == {"giveaways.entries": 1}
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
        "CREATE TABLE plugin_giveaways.notes (guild_id bigint NOT NULL, author_member_id bigint, winner_ids bigint[])"
    )
    problems = await schema_problems(harness.admin, "plugin_giveaways")
    assert any("notes.author_member_id" in p and "type teabot.member_id" in p for p in problems)
    assert any("notes.winner_ids" in p and "teabot.member_id[]" in p for p in problems)
