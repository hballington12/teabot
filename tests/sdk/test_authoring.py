"""Writing a plugin with `Plugin` and its decorators, through the real loader, migrations and call path."""

from pathlib import Path
from typing import Annotated, Any

import discord
import pytest
from pydantic import BaseModel, Field

from teabot.adapters.schema import slash_fields
from teabot.core.plans import canonical, diff_hash
from teabot.sdk import (
    DESTRUCTIVE,
    READ,
    ActionError,
    Context,
    Diff,
    DiffEntry,
    Plugin,
    TextChannel,
)
from teabot.sdk._signature import SignatureError
from teabot.testing import ActionFailed, FakeChannel, Planned, PluginHarness, Queued, Refused

MIGRATIONS = Path(__file__).parent / "authoring_migrations"


class Cfg(BaseModel):
    greeting: str = "hello"


class Said(BaseModel):
    channel: str
    times: int


class Row(BaseModel):
    text: str


plugin = Plugin("parrot", config=Cfg, migrations=MIGRATIONS)
type Ctx = Context[Cfg]


@plugin.action(needs="manage_messages")
async def say(
    ctx: Ctx, channel: TextChannel, text: str, times: Annotated[int, Field(ge=1, le=3)] = 1
) -> Said:
    """Say something in a channel.

    Args:
        channel: Where to say it.
        text: What to say.
        times: How many times to say it.
    """
    for _ in range(times):
        await channel.send(f"{ctx.config.greeting}: {text}")
    await ctx.db.execute("INSERT INTO said (guild_id, text) VALUES ($1, $2)", ctx.guild.id, text)
    return Said(channel=channel.name, times=times)


@plugin.action(risk=READ, reply="public")
async def list_(ctx: Ctx) -> list[Row]:
    """Everything said here."""
    return [
        Row(text=r["text"])
        for r in await ctx.db.fetch("SELECT text FROM said WHERE guild_id = $1", ctx.guild.id)
    ]


@plugin.action(risk=READ)
async def whoami(ctx: Ctx) -> str:
    """Who is asking."""
    return f"{ctx.actor.user_id} via {ctx.actor.via}"


@plugin.action(risk=DESTRUCTIVE, needs="manage_messages")
async def forget(ctx: Ctx) -> str:
    """Forget everything said here."""
    await ctx.db.execute("DELETE FROM said WHERE guild_id = $1", ctx.guild.id)
    return "forgotten"


@forget.plan
async def plan_forget(ctx: Ctx) -> Diff:
    rows = await ctx.db.fetch("SELECT text FROM said WHERE guild_id = $1", ctx.guild.id)
    return Diff(entries=[DiffEntry(change="remove", target=r["text"]) for r in rows])


@plugin.job
async def echo(ctx: Ctx, text: str) -> None:
    await ctx.db.execute("INSERT INTO said (guild_id, text) VALUES ($1, $2)", ctx.guild.id, f"echo {text}")


async def harnessed(teabot_harness: Any) -> PluginHarness:
    return await teabot_harness(plugin)


async def test_an_action_takes_its_inputs_as_parameters(teabot_harness: Any) -> None:
    harness = await harnessed(teabot_harness)
    channel = harness.guild.add_channel(FakeChannel(name="general"))
    out = await harness.invoke("parrot.say", {"channel": str(channel.id), "text": "hi", "times": 2})
    assert out == Said(channel="general", times=2)
    assert [m.content for m in channel.sent] == ["hello: hi", "hello: hi"]


async def test_a_channel_that_is_not_there_is_told_to_the_member(teabot_harness: Any) -> None:
    harness = await harnessed(teabot_harness)
    with pytest.raises(ActionFailed) as caught:
        await harness.invoke("parrot.say", {"channel": "123", "text": "hi"})
    assert caught.value.public_message == "That channel is not a text channel in this server."


async def test_limits_from_annotated_are_checked_and_reach_discord(teabot_harness: Any) -> None:
    harness = await harnessed(teabot_harness)
    channel = harness.guild.add_channel(FakeChannel())
    with pytest.raises(Refused) as caught:
        await harness.invoke("parrot.say", {"channel": str(channel.id), "text": "hi", "times": 9})
    assert caught.value.code == "invalid_input"
    options = {o["name"]: o for o in slash_fields(harness.registry.actions["parrot.say"].input).options}
    assert (options["times"]["min_value"], options["times"]["max_value"]) == (1, 3)
    assert options["channel"]["description"] == "Where to say it." and options["channel"]["type"] == 7


async def test_needs_is_checked_on_every_call(teabot_harness: Any) -> None:
    harness = await harnessed(teabot_harness)
    member = harness.guild.add_member(discord.Permissions.none())
    with pytest.raises(Refused) as caught:
        await harness.invoke("parrot.say", {"channel": "1", "text": "hi"}, user=member.id)
    assert caught.value.code == "forbidden"


async def test_names_summaries_and_replies_come_from_the_function(teabot_harness: Any) -> None:
    harness = await harnessed(teabot_harness)
    specs = harness.registry.actions
    assert sorted(n for n in specs if n.startswith("parrot.")) == [
        "parrot.forget",
        "parrot.list",
        "parrot.prune",
        "parrot.say",
        "parrot.whoami",
    ]
    assert specs["parrot.say"].summary == "Say something in a channel."
    assert (specs["parrot.list"].reply, specs["parrot.say"].reply) == ("public", "private")


async def test_a_list_and_a_string_are_replies(teabot_harness: Any) -> None:
    harness = await harnessed(teabot_harness)
    channel = harness.guild.add_channel(FakeChannel())
    await harness.invoke("parrot.say", {"channel": str(channel.id), "text": "one"})
    listed = await harness.invoke("parrot.list")
    assert listed.model_dump() == {"items": [{"text": "one"}]}
    assert harness.registry.actions["parrot.list"].render is not None
    assert harness.registry.actions["parrot.list"].render(listed) == "- one"
    who = await harness.invoke("parrot.whoami")
    assert who.model_dump() == {"text": f"{harness.member.id} via slash"}


async def test_a_destructive_action_plans_first(teabot_harness: Any) -> None:
    harness = await harnessed(teabot_harness)
    channel = harness.guild.add_channel(FakeChannel())
    await harness.invoke("parrot.say", {"channel": str(channel.id), "text": "secret"})
    plan = await harness.invoke("parrot.forget")
    assert isinstance(plan, Planned) and [e.target for e in plan.entries] == ["secret"]
    await harness.invoke("parrot.forget", {"confirm": plan.confirm})
    await harness.run_jobs()
    assert await harness.admin.fetchval("SELECT count(*) FROM plugin_parrot.said") == 0


async def test_a_job_takes_its_payload_as_parameters(teabot_harness: Any) -> None:
    harness = await harnessed(teabot_harness)
    await harness.admin.execute(
        "INSERT INTO core.jobs (guild_id, plugin_id, handler, payload) VALUES ($1, 'parrot', 'echo', $2)",
        harness.guild.id,
        '{"text": "back"}',
    )
    await harness.run_jobs()
    assert await harness.admin.fetchval("SELECT text FROM plugin_parrot.said") == "echo back"


def test_the_manifest_is_worked_out_from_the_plugin() -> None:
    manifest = plugin.manifest
    assert (manifest.id, manifest.version, manifest.config, manifest.migrations) == (
        "parrot",
        "0.0.0",
        Cfg,
        MIGRATIONS,
    )


def problems() -> Plugin[Cfg]:
    return Plugin("problems", config=Cfg)


def test_an_input_without_a_description_fails_where_it_is_written() -> None:
    async def act(ctx: Ctx, text: str) -> str:
        """Act."""
        return text

    with pytest.raises(
        SignatureError, match=r"test_authoring\.py:\d+: problems\.act has no description for text"
    ):
        problems().action()(act)


def test_a_description_over_discords_limit_fails() -> None:
    async def act(ctx: Ctx, text: str) -> str:
        return text

    act.__doc__ = f"Act.\n\nArgs:\n    text: {'x' * 101}\n"
    with pytest.raises(SignatureError, match="Discord allows 100"):
        problems().action()(act)


def test_an_args_entry_for_no_parameter_fails() -> None:
    async def act(ctx: Ctx) -> str:
        """Act.

        Args:
            ghost: Not a parameter.
        """
        return ""

    with pytest.raises(SignatureError, match="names ghost, which it does not take"):
        problems().action()(act)


def test_a_context_for_another_config_fails() -> None:
    class Other(BaseModel):
        pass

    async def act(ctx: Context[Other]) -> str:
        """Act."""
        return ""

    with pytest.raises(SignatureError, match=r"takes Context\[Other\], but the plugin's config is Cfg"):
        problems().action()(act)  # pyright: ignore[reportArgumentType]


async def test_a_destructive_action_without_a_plan_fails_to_load(teabot_harness: Any) -> None:
    broken = Plugin("broken")

    @broken.action(risk=DESTRUCTIVE)
    async def wipe(ctx: Context[Any]) -> str:  # pyright: ignore[reportUnusedFunction]
        """Wipe everything."""
        raise ActionError("never runs")

    with pytest.raises(RuntimeError, match=r"broken\.wipe is destructive and needs a plan"):
        await teabot_harness(broken)


@plugin.action(risk=DESTRUCTIVE)
async def prune(ctx: Ctx, text: str) -> str:
    """Remove what was said with this text.

    Args:
        text: The text to remove.
    """
    keys = [entry.key for entry in ctx.diff.entries]
    await ctx.db.execute("DELETE FROM said WHERE guild_id = $1 AND ctid::text = ANY($2)", ctx.guild.id, keys)
    return f"removed {len(keys)}"


@prune.plan
async def plan_prune(ctx: Ctx, text: str) -> Diff:
    rows = await ctx.db.fetch(
        "SELECT ctid::text AS row, text FROM said WHERE guild_id = $1 AND text = $2", ctx.guild.id, text
    )
    return Diff(entries=[DiffEntry(change="remove", target=r["text"], key=r["row"]) for r in rows])


async def test_the_apply_receives_the_confirmed_diff_with_its_keys(teabot_harness: Any) -> None:
    harness = await harnessed(teabot_harness)
    channel = harness.guild.add_channel(FakeChannel())
    for text in ("keep", "drop", "drop"):
        await harness.invoke("parrot.say", {"channel": str(channel.id), "text": text})
    plan = await harness.invoke("parrot.prune", {"text": "drop"})
    assert isinstance(plan, Planned) and plan.total == 2
    await harness.invoke("parrot.prune", {"text": "drop", "confirm": plan.confirm})
    await harness.run_jobs()
    assert await harness.admin.fetchval("SELECT array_agg(text) FROM plugin_parrot.said") == ["keep"]


def test_a_key_is_part_of_the_hash_and_an_entry_without_one_hashes_as_before() -> None:
    plain = Diff(entries=[DiffEntry(change="remove", target="x")])
    keyed = Diff(entries=[DiffEntry(change="remove", target="x", key=1)])
    other = Diff(entries=[DiffEntry(change="remove", target="x", key=2)])
    assert diff_hash(keyed) != diff_hash(other) and diff_hash(plain) != diff_hash(keyed)
    assert canonical(plain) == '[{"change":"remove","target":"x","detail":null}]'


async def test_an_apply_job_is_labelled_with_the_action_it_applies(teabot_harness: Any) -> None:
    harness = await harnessed(teabot_harness)
    plan = await harness.invoke("parrot.forget")
    assert isinstance(plan, Planned)
    queued = await harness.invoke("parrot.forget", {"confirm": plan.confirm})
    assert isinstance(queued, Queued)
    status = (await harness.invoke("admin.job_status", {"job_id": queued.job_id})).model_dump()
    assert (status["label"], status["started_by"]) == ("parrot.forget", harness.member.id)
