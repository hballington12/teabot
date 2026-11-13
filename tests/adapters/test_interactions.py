"""The interaction router (WP2.7, D29, D32): slash commands, LongText modals, replies and refusals."""

from dataclasses import dataclass, field
from typing import Any

import discord
import pytest
from pydantic import BaseModel

from teapot.adapters.interactions import InteractionRouter, default_embed
from teapot.core.registry import ActionFailed, Call, Refused
from teapot.db.migrate import migrate
from teapot.db.naming import Naming
from teapot.db.pool import Pools
from teapot.db.types import Conn
from teapot.sdk import ActionSpec, ChannelRef, LongText, Risk, UntrustedText

GUILD, USER, CHANNEL = 1001, 2001, 3001


class Post(BaseModel):
    channel: ChannelRef
    title: str
    body: LongText


class Posted(BaseModel):
    message_id: int
    preview: UntrustedText


class Ping(BaseModel):
    pass


class Pong(BaseModel):
    ok: bool


async def never(_ctx: Any, _data: Any) -> Any:
    raise AssertionError("the registry fake runs actions")


POST = ActionSpec("announcements.post", "Post an announcement", Post, Posted, Risk.WRITE, never)
PING = ActionSpec(
    "announcements.ping", "Ping", Ping, Pong, Risk.READ, never, render=lambda out: f"pong {out.ok}"
)


@dataclass
class FakeRegistry:
    actions: dict[str, ActionSpec[Any, Any]]
    calls: list[Call] = field(default_factory=list[Call])
    result: BaseModel | Exception | None = None

    async def invoke(self, call: Call) -> BaseModel:
        self.calls.append(call)
        if isinstance(self.result, Exception):
            raise self.result
        assert self.result is not None
        return self.result


@dataclass
class FakeResponse:
    events: list[tuple[Any, ...]]

    async def defer(self, *, ephemeral: bool = False, thinking: bool = False) -> None:
        self.events.append(("defer", ephemeral, thinking))

    async def send_modal(self, modal: discord.ui.Modal) -> None:
        self.events.append(("modal", modal))

    async def send_message(self, content: str | None = None, *, ephemeral: bool = False, **_: Any) -> None:
        self.events.append(("message", content, ephemeral))


@dataclass
class FakeFollowup:
    events: list[tuple[Any, ...]]

    async def send(
        self, content: str | None = None, *, embed: discord.Embed | None = None, ephemeral: bool = False
    ) -> None:
        self.events.append(("followup", content if embed is None else embed, ephemeral))


@dataclass
class FakeUser:
    id: int


class FakeInteraction:
    def __init__(
        self, kind: discord.InteractionType, data: dict[str, Any], guild_id: int | None = GUILD
    ) -> None:
        self.type = kind
        self.data = data
        self.guild_id = guild_id
        self.user = FakeUser(USER)
        self.events: list[tuple[Any, ...]] = []
        self.response = FakeResponse(self.events)
        self.followup = FakeFollowup(self.events)


def command(sub: str, options: list[dict[str, Any]]) -> FakeInteraction:
    data = {"name": "announcements", "options": [{"name": sub, "type": 1, "options": options}]}
    return FakeInteraction(discord.InteractionType.application_command, data)


def modal_submit(custom_id: str, values: dict[str, str]) -> FakeInteraction:
    rows = [{"type": 1, "components": [{"type": 4, "custom_id": k, "value": v}]} for k, v in values.items()]
    return FakeInteraction(discord.InteractionType.modal_submit, {"custom_id": custom_id, "components": rows})


@pytest.fixture
async def router(admin: Conn, naming: Naming, pools: Pools) -> tuple[InteractionRouter, FakeRegistry]:
    await migrate(admin, naming, [])
    registry = FakeRegistry({POST.name: POST, PING.name: PING})
    return InteractionRouter(registry, pools.core_db()), registry


async def test_a_command_without_long_text_defers_runs_and_replies_through_its_renderer(
    router: tuple[InteractionRouter, FakeRegistry],
) -> None:
    r, registry = router
    registry.result = Pong(ok=True)
    interaction = command("ping", [])
    await r.handle(interaction)
    assert registry.calls == [Call("announcements.ping", GUILD, registry.calls[0].actor, {})]
    assert registry.calls[0].actor.user_id == USER and registry.calls[0].actor.via == "slash"
    assert interaction.events == [("defer", True, True), ("followup", "pong True", True)]


async def test_a_command_with_long_text_opens_a_modal_and_the_submit_runs_it(
    router: tuple[InteractionRouter, FakeRegistry], admin: Conn
) -> None:
    r, registry = router
    first = command(
        "post",
        [{"name": "channel", "type": 7, "value": str(CHANNEL)}, {"name": "title", "type": 3, "value": "Hi"}],
    )
    await r.handle(first)
    ((kind, modal),) = first.events
    assert kind == "modal" and [c.custom_id for c in modal.children] == ["body"]
    assert registry.calls == []
    registry.result = Posted(message_id=9, preview="Hi there")
    submit = modal_submit(modal.custom_id, {"body": "Line one\nLine two"})
    await r.handle(submit)
    (call,) = registry.calls
    assert call.action == "announcements.post"
    assert call.raw_input == {"channel": str(CHANNEL), "title": "Hi", "body": "Line one\nLine two"}
    assert submit.events[0] == ("defer", True, True)
    kind, embed, ephemeral = submit.events[1]
    assert (kind, ephemeral) == ("followup", True) and isinstance(embed, discord.Embed)
    assert await admin.fetchval("SELECT count(*) FROM core.interaction_drafts") == 0


async def test_a_modal_submitted_by_someone_else_is_refused(
    router: tuple[InteractionRouter, FakeRegistry],
) -> None:
    r, registry = router
    first = command(
        "post",
        [{"name": "channel", "type": 7, "value": str(CHANNEL)}, {"name": "title", "type": 3, "value": "Hi"}],
    )
    await r.handle(first)
    modal = first.events[0][1]
    submit = modal_submit(modal.custom_id, {"body": "x"})
    submit.user = FakeUser(USER + 1)
    await r.handle(submit)
    assert registry.calls == [] and submit.events == [
        ("message", "That form has expired. Run the command again.", True)
    ]


async def test_an_unknown_or_expired_draft_is_refused(router: tuple[InteractionRouter, FakeRegistry]) -> None:
    r, registry = router
    submit = modal_submit("teapot:core:modal:00000000-0000-0000-0000-000000000000", {"body": "x"})
    await r.handle(submit)
    assert registry.calls == [] and submit.events == [
        ("message", "That form has expired. Run the command again.", True)
    ]


async def test_a_refusal_is_told_to_the_member_privately(
    router: tuple[InteractionRouter, FakeRegistry],
) -> None:
    r, registry = router
    registry.result = Refused("forbidden", "announcements.ping needs permissions you do not have")
    interaction = command("ping", [])
    await r.handle(interaction)
    assert interaction.events[-1] == (
        "followup",
        "announcements.ping needs permissions you do not have",
        True,
    )


async def test_a_failure_is_reported_without_its_details(
    router: tuple[InteractionRouter, FakeRegistry],
) -> None:
    r, registry = router
    registry.result = ActionFailed("RuntimeError('secret detail')")
    interaction = command("ping", [])
    await r.handle(interaction)
    assert interaction.events[-1] == ("followup", "That did not work. The error is in the audit log.", True)


async def test_commands_outside_a_server_are_refused(router: tuple[InteractionRouter, FakeRegistry]) -> None:
    r, registry = router
    interaction = command("ping", [])
    interaction.guild_id = None
    await r.handle(interaction)
    assert registry.calls == [] and interaction.events == [
        ("message", "teapot commands work inside a server.", True)
    ]


async def test_interactions_that_are_not_teapots_are_ignored(
    router: tuple[InteractionRouter, FakeRegistry],
) -> None:
    r, registry = router
    other = modal_submit("someone-elses-modal", {"x": "y"})
    await r.handle(other)
    assert other.events == [] and registry.calls == []


def test_the_default_embed_shows_each_output_field() -> None:
    embed = default_embed(POST, Posted(message_id=9, preview="Hi there"))
    assert embed.title == "Post an announcement"
    assert [(f.name, f.value) for f in embed.fields] == [("Message id", "9"), ("Preview", "Hi there")]


async def test_an_action_error_is_shown_to_the_member(router: tuple[InteractionRouter, FakeRegistry]) -> None:
    r, registry = router
    registry.result = ActionFailed("ActionError('no')", public_message="that channel is not a text channel")
    interaction = command("ping", [])
    await r.handle(interaction)
    assert interaction.events[-1] == ("followup", "that channel is not a text channel", True)
