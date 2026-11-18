"""Member labels: a plugin that declares `writes=["labels"]` replaces its labels for a server at once, filters
match them while they are fresh and the plugin is on, and a change fires `labels_changed`."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from teabot.core.registry import Call
from teabot.sdk import READ, Actor, Context, EmptyConfig, MemberFilter, Plugin
from teabot.testing import HarnessFactory, PluginHarness

tagger = Plugin("tagger", reads=["members"], writes=["labels"])
blind = Plugin("blind")
heard: list[str] = []


@tagger.action(risk=READ)
async def tag(ctx: Context[EmptyConfig], members: str, label: str) -> str:
    """Replace the labels: `label` for each listed member, none for anyone else.

    Args:
        members: Member IDs, separated by commas.
        label: The label to give them.
    """
    ids = [int(m) for m in members.split(",") if m]
    return str(await ctx.labels.replace_all({i: [label] for i in ids}, as_of=datetime.now(UTC)))


@tagger.action(risk=READ)
async def count(ctx: Context[EmptyConfig], label: str, role: int = 0) -> str:
    """Count members with a label, and a role when given.

    Args:
        label: The label.
        role: A role they must also have, or 0.
    """
    filters = [MemberFilter(labels_from="tagger", labels_any=[label])]
    if role:
        filters.append(MemberFilter(roles_any=[role]))
    return str(await ctx.members.count(*filters))


@tagger.on_labels_changed
async def changed(ctx: Context[EmptyConfig], plugin_id: str) -> None:
    heard.append(plugin_id)


@blind.action(risk=READ)
async def peek(ctx: Context[EmptyConfig]) -> str:
    """Try to write labels."""
    return str(await ctx.labels.replace_all({}, as_of=datetime.now(UTC)))


async def directory(harness: PluginHarness, *, ready: bool = True) -> None:
    db: Any = harness.admin
    guild = harness.guild.id
    await db.execute("INSERT INTO core.directory_state (guild_id, backfilled) VALUES ($1, $2)", guild, ready)
    for user_id, name, roles in ((1, "alice", [7]), (2, "bob", [7]), (3, "cat", [8])):
        await db.execute(
            "INSERT INTO core.members (guild_id, user_id, name, role_ids, observed_at) VALUES ($1, $2, $3, $4, now())",
            guild,
            user_id,
            name,
            roles,
        )


async def text(harness: PluginHarness, action: str, raw: dict[str, Any]) -> str:
    reply = await harness.invoke(action, raw)
    return str(reply.model_dump()["text"])


async def test_labels_replace_the_whole_set_and_filters_match_them(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(tagger)
    await directory(harness)
    assert await text(harness, "tagger.tag", {"members": "1,3", "label": "in_clan"}) == "2"
    assert await text(harness, "tagger.count", {"label": "in_clan"}) == "2"
    assert await text(harness, "tagger.count", {"label": "in_clan", "role": 7}) == "1"
    # A replace without a member drops theirs, and an unchanged member is not written again.
    assert await text(harness, "tagger.tag", {"members": "3", "label": "in_clan"}) == "1"
    assert await text(harness, "tagger.count", {"label": "in_clan"}) == "1"


async def test_stale_labels_match_nobody(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(tagger)
    await directory(harness)
    await text(harness, "tagger.tag", {"members": "1,2", "label": "in_clan"})
    db: Any = harness.admin
    await db.execute("UPDATE core.label_state SET as_of = now() - interval '2 days'")
    assert await text(harness, "tagger.count", {"label": "in_clan"}) == "0"


async def test_a_disabled_plugins_labels_do_not_count(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(tagger)
    await directory(harness)
    await text(harness, "tagger.tag", {"members": "1", "label": "in_clan"})
    labels = harness.registry.labels
    assert labels is not None
    assert await labels.live(harness.guild.id, "tagger")
    db: Any = harness.admin
    await db.execute("UPDATE core.guild_plugins SET enabled = false WHERE plugin_id = 'tagger'")
    assert not await labels.live(harness.guild.id, "tagger")
    assert not await labels.live(harness.guild.id, "nobody")


async def test_a_change_fires_labels_changed_and_a_repeat_does_not(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(tagger)
    await directory(harness)
    heard.clear()
    await text(harness, "tagger.tag", {"members": "1", "label": "in_clan"})
    await harness.run_jobs()
    assert heard == ["tagger"]
    await text(harness, "tagger.tag", {"members": "1", "label": "in_clan"})
    await harness.run_jobs()
    assert heard == ["tagger"]


async def test_labels_becoming_fresh_again_fire_labels_changed(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(tagger)
    await directory(harness)
    await text(harness, "tagger.tag", {"members": "1", "label": "in_clan"})
    await harness.run_jobs()
    heard.clear()
    db: Any = harness.admin
    await db.execute("UPDATE core.label_state SET as_of = now() - interval '2 days'")
    await text(harness, "tagger.tag", {"members": "1", "label": "in_clan"})
    await harness.run_jobs()
    assert heard == ["tagger"]


async def test_a_refused_label_says_why(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(tagger)
    await directory(harness)
    with pytest.raises(Exception, match="not a label"):
        await harness.invoke("tagger.tag", {"members": "1", "label": "in clan"})


async def test_labels_wait_for_the_directory(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(tagger)
    await directory(harness, ready=False)
    with pytest.raises(Exception, match="not ready"):
        await harness.invoke("tagger.tag", {"members": "1", "label": "in_clan"})


async def test_a_plugin_that_did_not_declare_them_cannot_write_labels(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(blind)
    await directory(harness)
    with pytest.raises(Exception, match="writes="):
        await harness.invoke("blind.peek", {})


def test_a_filter_on_labels_names_their_plugin() -> None:
    with pytest.raises(ValueError, match="labels_from"):
        MemberFilter(labels_any=["in_clan"])


def test_a_freshness_window_is_at_most_a_week() -> None:
    with pytest.raises(Exception, match="at most a week"):
        Plugin("eager", writes=["labels"], labels_fresh_for=timedelta(days=8))


async def test_admin_members_filters_on_labels_too(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(tagger)
    await directory(harness)
    await text(harness, "tagger.tag", {"members": "2", "label": "in_clan"})
    actor = Actor(harness.member.id, "mcp", None)  # pyright: ignore[reportArgumentType]
    raw = {"labels_from": "tagger", "labels_any": ["in_clan"]}
    page = await harness.registry.invoke(Call("admin.members", harness.guild.id, actor, raw))
    assert page.model_dump()["total"] == 1
