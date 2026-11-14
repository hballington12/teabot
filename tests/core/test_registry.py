"""The action registry and its call path (WP2.3, D1, D2, D18, D19, D24)."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import discord
import pytest
from pydantic import BaseModel

from teabot.core.loader import Loaded
from teabot.core.registry import (
    ActionFailed,
    Call,
    PluginActionContext,
    Refused,
    Registry,
    TokenLimits,
    sources_from,
)
from teabot.db.migrate import PluginMigrations, migrate
from teabot.db.naming import Naming
from teabot.db.pool import Pools
from teabot.db.types import Conn
from teabot.sdk import ActionContext, ActionError, ActionSpec, Actor, Manifest, Risk, Surface
from teabot.testing import FakeClient, FakeGuild, FakeMember

GUILD, MEMBER, STRANGER, UNCACHED = 1001, 2001, 2002, 2003


class Count(BaseModel):
    pass


class Counted(BaseModel):
    total: int
    limit: int


class Add(BaseModel):
    name: str


class Added(BaseModel):
    job_id: int


class AlphaConfig(BaseModel):
    limit: int = 3


async def count(ctx: ActionContext, _data: Count) -> Counted:
    config = ctx.config
    assert isinstance(config, AlphaConfig)
    return Counted(total=await ctx.db.fetchval("SELECT count(*) FROM entries"), limit=config.limit)


async def add(ctx: ActionContext, data: Add) -> Added:
    async with ctx.db.transaction() as tx:
        await tx.execute("INSERT INTO entries (guild_id, name) VALUES ($1, $2)", ctx.guild.id, data.name)
        job_id = await tx.schedule("announce", payload={"name": data.name})
    return Added(job_id=job_id)


async def boom(_ctx: ActionContext, _data: Count) -> Counted:
    raise RuntimeError("it broke")


async def refuse_politely(_ctx: ActionContext, _data: Count) -> Counted:
    raise ActionError("that channel is not a text channel")


MANAGE = discord.Permissions(manage_messages=True)
SPECS = [
    ActionSpec("alpha.count", "Count entries", Count, Counted, Risk.READ, count),
    ActionSpec(
        "alpha.nomcp",
        "Count, not over MCP",
        Count,
        Counted,
        Risk.READ,
        count,
        surfaces=Surface.SLASH | Surface.SERVICE,
    ),
    ActionSpec("alpha.add", "Add an entry", Add, Added, Risk.WRITE, add, default_permissions=MANAGE),
    ActionSpec("alpha.boom", "Fail", Count, Counted, Risk.WRITE, boom),
    ActionSpec("alpha.polite", "Fail with a message", Count, Counted, Risk.WRITE, refuse_politely),
]


@dataclass
class RecordingAudit:
    events: list[tuple[str, Any]] = field(default_factory=list[tuple[str, Any]])

    async def started(self, call: Any) -> int:
        self.events.append(("started", call.action))
        return len(self.events)

    async def finished(self, audit_id: int, outcome: str, error: str | None) -> None:
        self.events.append(("finished", (audit_id, outcome, error)))

    async def single(self, call: Any, outcome: str, error: str | None) -> None:
        self.events.append(("single", (call.action, outcome, error)))


@dataclass
class World:
    registry: Registry
    audit: RecordingAudit
    admin: Conn


@pytest.fixture
async def world(admin: Conn, naming: Naming, pools: Pools, tmp_path: Path) -> World:
    directory = tmp_path / "alpha"
    directory.mkdir()
    (directory / "0001_entries.sql").write_text("CREATE TABLE entries (guild_id bigint NOT NULL, name text);")
    await migrate(admin, naming, [PluginMigrations("alpha", directory)])
    await admin.execute(
        "INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled) VALUES ($1, 'alpha', true)", GUILD
    )
    plugin = _Plugin(Manifest("alpha", "1.0", config=AlphaConfig))
    loaded = {"alpha": Loaded(plugin, {s.name: s for s in SPECS})}
    guild = FakeGuild(
        GUILD,
        {MEMBER: FakeMember(MEMBER, MANAGE), STRANGER: FakeMember(STRANGER, discord.Permissions.none())},
        {UNCACHED: FakeMember(UNCACHED, MANAGE)},
    )
    audit = RecordingAudit()
    registry = Registry(
        sources_from(loaded),
        pools=pools,
        client=FakeClient({GUILD: guild}),
        audit=audit,
    )
    return World(registry, audit, admin)


@dataclass
class _Plugin:
    manifest: Manifest

    def setup(self, registrar: Any) -> None:
        return None


def call(action: str, raw: dict[str, Any] | None = None, *, user: int = MEMBER, guild: int = GUILD) -> Call:
    return Call(action, guild, Actor(user, "slash"), raw or {})


async def refused(world: World, c: Call) -> Refused:
    with pytest.raises(Refused) as caught:
        await world.registry.invoke(c)
    return caught.value


async def test_an_unknown_action_is_refused(world: World) -> None:
    assert (await refused(world, call("alpha.nope"))).code == "unknown_action"


async def test_a_server_the_bot_is_not_in_is_refused(world: World) -> None:
    assert (await refused(world, call("alpha.count", guild=9999))).code == "not_in_guild"


async def test_a_plugin_not_enabled_in_the_server_is_refused(world: World) -> None:
    await world.admin.execute("UPDATE core.guild_plugins SET enabled = false")
    assert (await refused(world, call("alpha.count"))).code == "plugin_not_enabled"


async def test_invalid_input_is_refused_with_the_reason(world: World) -> None:
    error = await refused(world, call("alpha.add", {"name": 5}))
    assert error.code == "invalid_input" and "name" in error.message


async def test_a_member_without_the_permission_is_refused_and_audited(world: World) -> None:
    assert (await refused(world, call("alpha.add", {"name": "x"}, user=STRANGER))).code == "forbidden"
    assert world.audit.events == [("single", ("alpha.add", "refused", "forbidden"))]


async def test_an_uncached_member_is_fetched_and_checked(world: World) -> None:
    out = await world.registry.invoke(call("alpha.add", {"name": "x"}, user=UNCACHED))
    assert isinstance(out, Added)


async def test_someone_not_in_the_server_is_refused(world: World) -> None:
    assert (await refused(world, call("alpha.count", user=999))).code == "forbidden"


async def test_a_read_gets_its_plugins_config_and_one_audit_row(world: World) -> None:
    await world.admin.execute("UPDATE core.guild_plugins SET config = '{\"limit\": 9}'")
    out = await world.registry.invoke(call("alpha.count"))
    assert out == Counted(total=0, limit=9)
    assert world.audit.events == [("single", ("alpha.count", "ok", None))]


async def test_a_write_is_audited_before_and_after_and_queues_its_job_for_the_server(world: World) -> None:
    out = await world.registry.invoke(call("alpha.add", {"name": "x"}))
    assert isinstance(out, Added)
    assert world.audit.events == [("started", "alpha.add"), ("finished", (1, "ok", None))]
    job = await world.admin.fetchrow(
        "SELECT guild_id, plugin_id, handler, payload FROM core.jobs WHERE id = $1", out.job_id
    )
    assert job is not None and (job["guild_id"], job["plugin_id"], job["handler"]) == (
        GUILD,
        "alpha",
        "announce",
    )
    assert json.loads(job["payload"]) == {"name": "x"}
    assert (
        await world.admin.fetchval("SELECT count(*) FROM plugin_alpha.entries WHERE guild_id = $1", GUILD)
        == 1
    )


async def test_a_failing_action_is_audited_as_an_error_and_raised(world: World) -> None:
    with pytest.raises(ActionFailed, match="it broke"):
        await world.registry.invoke(call("alpha.boom"))
    assert world.audit.events[-1] == ("finished", (1, "error", "RuntimeError('it broke')"))


def test_the_registry_lists_its_actions(world: World) -> None:
    assert set(world.registry.actions) == {
        "alpha.count",
        "alpha.nomcp",
        "alpha.add",
        "alpha.boom",
        "alpha.polite",
    }


async def test_an_action_error_carries_a_message_for_the_member(world: World) -> None:
    with pytest.raises(ActionFailed) as caught:
        await world.registry.invoke(call("alpha.polite"))
    assert caught.value.public_message == "that channel is not a text channel"
    assert world.audit.events[-1] == ("finished", (1, "error", "that channel is not a text channel"))


async def test_other_failures_carry_no_public_message(world: World) -> None:
    with pytest.raises(ActionFailed) as caught:
        await world.registry.invoke(call("alpha.boom"))
    assert caught.value.public_message is None


def test_a_builtin_context_has_no_plugin_database() -> None:
    ctx = PluginActionContext(None, Actor(1, "slash"), AlphaConfig(), None)
    with pytest.raises(RuntimeError, match="core services"):
        _ = ctx.queue


def token_call(
    action: str,
    raw: dict[str, Any] | None = None,
    *,
    via: Any = "mcp",
    risk: Risk = Risk.WRITE,
    allowed: frozenset[str] = frozenset(),
) -> Call:
    return Call(action, GUILD, Actor(MEMBER, via, "tok1"), raw or {}, TokenLimits(risk, allowed))


async def test_a_token_call_above_the_tokens_maximum_risk_is_refused(world: World) -> None:
    refusal = await refused(world, token_call("alpha.add", {"name": "x"}, risk=Risk.READ))
    assert refusal.code == "above_token_risk"
    assert await world.registry.invoke(token_call("alpha.count", risk=Risk.READ)) is not None


async def test_a_token_with_an_allow_list_reaches_only_those_actions(world: World) -> None:
    allowed = frozenset({"alpha.count"})
    assert (
        await refused(world, token_call("alpha.add", {"name": "x"}, allowed=allowed))
    ).code == "not_allowed_by_token"
    assert await world.registry.invoke(token_call("alpha.count", allowed=allowed)) is not None


@pytest.mark.parametrize(("via", "code"), [("mcp", "wrong_surface"), ("service", None), ("slash", None)])
async def test_an_action_is_reached_only_through_its_surfaces(
    world: World, via: Any, code: str | None
) -> None:
    c = token_call("alpha.nomcp", via=via)
    if code is None:
        assert await world.registry.invoke(c) is not None
    else:
        assert (await refused(world, c)).code == code
