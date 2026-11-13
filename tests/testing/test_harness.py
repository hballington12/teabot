"""`teapot.testing` (WP2.8, D45): plugin authors test through the real loader, migrations and call path."""

from pathlib import Path
from typing import Any, cast

import discord
import pytest
from pydantic import BaseModel

from teapot.core.registry import Refused
from teapot.sdk import ActionContext, ActionSpec, ChannelRef, Manifest, Registrar, Risk
from teapot.testing import FakeChannel, FakeGuild, PluginHarness

MANAGE = discord.Permissions(manage_messages=True)


class Say(BaseModel):
    channel: ChannelRef
    text: str


class Said(BaseModel):
    message_id: int
    stored: int


async def say(ctx: ActionContext, data: Say) -> Said:
    channel: Any = cast(Any, ctx.guild.get_channel(data.channel))
    assert channel is not None
    message = await channel.send(content=data.text)
    async with ctx.db.transaction() as tx:
        await tx.execute("INSERT INTO said (guild_id, text) VALUES ($1, $2)", ctx.guild.id, data.text)
        stored = await tx.fetchval("SELECT count(*) FROM said")
    return Said(message_id=int(message.id), stored=int(stored))


class Echo:
    def __init__(self, migrations: Path) -> None:
        self.manifest = Manifest("echo", "1.0", migrations=migrations)

    def setup(self, registrar: Registrar) -> None:
        registrar.action(
            ActionSpec("echo.say", "Say something", Say, Said, Risk.WRITE, say, default_permissions=MANAGE)
        )


@pytest.fixture
def echo(tmp_path: Path) -> Echo:
    directory = tmp_path / "echo"
    directory.mkdir()
    (directory / "0001_said.sql").write_text("CREATE TABLE said (guild_id bigint NOT NULL, text text);")
    return Echo(directory)


async def test_an_action_runs_through_the_real_call_path(teapot_harness: Any, echo: Echo) -> None:
    harness: PluginHarness = await teapot_harness(echo)
    channel = harness.guild.add_channel(FakeChannel(77))
    out = await harness.invoke("echo.say", {"channel": "77", "text": "hello"})
    assert isinstance(out, Said) and out.stored == 1
    assert channel.sent[0].content == "hello" and out.message_id == channel.sent[0].id
    assert (
        await harness.admin.fetchval("SELECT outcome FROM core.audit_log WHERE action = 'echo.say'") == "ok"
    )


async def test_permissions_are_checked_as_in_production(teapot_harness: Any, echo: Echo) -> None:
    harness: PluginHarness = await teapot_harness(echo)
    harness.guild.add_channel(FakeChannel(77))
    stranger = harness.guild.add_member(discord.Permissions.none())
    with pytest.raises(Refused) as caught:
        await harness.invoke("echo.say", {"channel": "77", "text": "hi"}, user=stranger.id)
    assert caught.value.code == "forbidden"


async def test_a_plugin_that_fails_to_load_says_why(teapot_harness: Any, tmp_path: Path) -> None:
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "0001_bad.sql").write_text("CREATE TABLE notes (body text);")
    with pytest.raises(RuntimeError, match="guild_id"):
        await teapot_harness(Echo(broken))


async def test_a_member_found_only_over_rest_is_checked_too(teapot_harness: Any, echo: Echo) -> None:
    harness: PluginHarness = await teapot_harness(echo)
    harness.guild.add_channel(FakeChannel(77))
    uncached = harness.guild.add_member(discord.Permissions(manage_messages=True), cached=False)
    assert harness.guild.get_member(uncached.id) is None
    out = await harness.invoke("echo.say", {"channel": "77", "text": "hi"}, user=uncached.id)
    assert isinstance(out, Said)


async def test_a_forbidden_channel_raises_like_discord() -> None:
    channel = FakeChannel(5, forbidden=True)
    with pytest.raises(discord.Forbidden):
        await channel.send(content="x")
    assert channel.sent == []


def test_members_are_cached_unless_asked_otherwise() -> None:
    guild = FakeGuild()
    cached = guild.add_member(discord.Permissions.none())
    rest_only = guild.add_member(discord.Permissions.none(), cached=False)
    assert guild.get_member(cached.id) is cached and guild.get_member(rest_only.id) is None
