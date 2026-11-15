"""ctx.store keeps a server's pydantic records by key, held to the server, and found by member deletion."""

import discord
import pytest
from pydantic import BaseModel

from teabot.core.member_data import delete_member_data
from teabot.sdk import Context, EmptyConfig, Member, Plugin
from teabot.testing import HarnessFactory, PluginHarness

plugin = Plugin("tally")
type Ctx = Context[EmptyConfig]


class Tally(BaseModel):
    count: int = 0


@plugin.action()
async def bump(ctx: Ctx, member: Member) -> str:
    """Count one for a member.

    Args:
        member: Who.
    """
    tallies = ctx.store(Tally)
    tally = await tallies.get(member) or Tally()
    tally.count += 1
    await tallies.put(member, tally)
    return str(tally.count)


@plugin.action()
async def note(ctx: Ctx, key: str, count: int) -> str:
    """Keep a count under a key.

    Args:
        key: The key.
        count: The count.
    """
    await ctx.store(Tally).put(key, Tally(count=count))
    return ",".join(f"{k}={v.count}" for k, v in (await ctx.store(Tally).all()).items())


@plugin.action()
async def forget(ctx: Ctx, key: str) -> str:
    """Forget a key.

    Args:
        key: The key.
    """
    return "gone" if await ctx.store(Tally).delete(key) else "none"


@pytest.fixture
async def harness(teabot_harness: HarnessFactory) -> PluginHarness:
    return await teabot_harness(plugin)


async def test_records_are_kept_read_and_removed_by_key(harness: PluginHarness) -> None:
    member = harness.guild.add_member(discord.Permissions.none())
    assert [await harness.call(bump, member=member) for _ in range(3)] == ["1", "2", "3"]
    assert await harness.call(note, key="raids", count=7) == f"member:{member.id}=3,raids=7"
    assert await harness.call(forget, key="raids") == "gone"
    assert await harness.call(forget, key="raids") == "none"


async def test_another_server_sees_none_of_them(harness: PluginHarness) -> None:
    await harness.call(note, key="raids", count=7)
    other = harness.pools.guild_plugin_db("tally", harness.guild.id + 1)
    assert await other.fetch("SELECT * FROM teabot_store") == []


async def test_deleting_a_members_data_removes_their_records(harness: PluginHarness) -> None:
    member = harness.guild.add_member(discord.Permissions.none())
    await harness.call(bump, member=member)
    deleted = await delete_member_data(harness.admin, harness.pools.naming, member.id)
    assert deleted.plugins == {"tally.teabot_store": 1}
