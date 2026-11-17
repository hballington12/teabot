"""`ctx.members` (D55): a plugin that declares `reads=["members"]` counts and finds present members by a
`MemberFilter`, in its own server only; one that does not is refused."""

from typing import Any

import pytest

from teabot.sdk import Context, EmptyConfig, MemberFilter, PeopleFilter, Plugin, READ
from teabot.testing import HarnessFactory, PluginHarness

reader = Plugin("reader", reads=["members"])
blind = Plugin("blind")


@reader.action(risk=READ)
async def count_role(ctx: Context[EmptyConfig], role: int) -> str:
    """Count members with a role.

    Args:
        role: The role's ID.
    """
    total = await ctx.members.count(PeopleFilter(roles_any=[role]))
    found = await ctx.members.find(MemberFilter(roles_any=[role]), limit=1)
    return f"{total} {[m.name for m in found]}"


@blind.action(risk=READ)
async def peek(ctx: Context[EmptyConfig]) -> str:
    """Try the directory."""
    return str(await ctx.members.count(MemberFilter()))


async def directory(harness: PluginHarness, *, ready: bool = True) -> None:
    db: Any = harness.admin
    guild = harness.guild.id
    await db.execute("INSERT INTO core.directory_state (guild_id, backfilled) VALUES ($1, $2)", guild, ready)
    for user_id, name, roles, bot in (
        (1, "alice", [7], False),
        (2, "bob", [7], False),
        (3, "robo", [7], True),
    ):
        await db.execute(
            "INSERT INTO core.members (guild_id, user_id, name, role_ids, bot, observed_at) "
            "VALUES ($1, $2, $3, $4, $5, now())",
            guild,
            user_id,
            name,
            roles,
            bot,
        )
    # Another server's member, whom the plugin must never see.
    await db.execute(
        "INSERT INTO core.members (guild_id, user_id, name, role_ids, observed_at) VALUES ($1, 4, 'eve', '{7}', now())",
        guild + 1,
    )


async def test_a_declared_plugin_counts_and_finds_its_servers_members(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(reader)
    await directory(harness)
    reply = await harness.invoke("reader.count_role", {"role": 7})
    assert reply.model_dump() == {"text": "2 ['alice']"}


async def test_before_the_backfill_the_plugin_is_told_why(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(reader)
    await directory(harness, ready=False)
    with pytest.raises(Exception, match="first copy"):
        await harness.invoke("reader.count_role", {"role": 7})


async def test_a_plugin_that_did_not_declare_it_cannot_read_it(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(blind)
    await directory(harness)
    with pytest.raises(Exception, match="reads="):
        await harness.invoke("blind.peek", {})


def test_reads_names_only_what_exists() -> None:
    with pytest.raises(Exception, match="reads"):
        Plugin("odd", reads=["messages"])
