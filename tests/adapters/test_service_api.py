"""The service API (WP4.4, D20): `POST /api/v1/actions/<name>` for event backends, with a token."""

import json
from collections.abc import AsyncIterator
from typing import Any, get_args

import discord
import httpx
import pytest
from pydantic import BaseModel

from teabot.adapters.service_api import STATUS
from teabot.auth.tokens import NewToken
from teabot.core.registry import RefusalCode
from teabot.health import Health
from teabot.sdk import (
    ActionContext,
    ActionError,
    ActionSpec,
    Diff,
    DiffEntry,
    Manifest,
    Registrar,
    Risk,
    Surface,
    UntrustedText,
)
from teabot.testing import PluginHarness
from teabot.web import build_app


class Post(BaseModel):
    text: str


class Posted(BaseModel):
    text: UntrustedText
    count: int


class NoInput(BaseModel):
    pass


async def post(ctx: ActionContext, data: Post) -> Posted:
    return Posted(text=data.text, count=1)


async def look(ctx: ActionContext, data: NoInput) -> NoInput:
    return data


async def sulk(ctx: ActionContext, data: NoInput) -> NoInput:
    raise ActionError("Not today.")


async def crash(ctx: ActionContext, data: NoInput) -> NoInput:
    raise RuntimeError("secret internals")


class Clear(BaseModel):
    prefix: str


async def clear_plan(ctx: ActionContext, data: Clear) -> Diff:
    return Diff(entries=[DiffEntry(change="remove", target="apple")])


async def clear(ctx: ActionContext, data: Clear) -> NoInput:
    return NoInput()


class Feed:
    manifest = Manifest("feed", "1.0")

    def setup(self, registrar: Registrar) -> None:
        manage = discord.Permissions(manage_messages=True)
        registrar.action(
            ActionSpec("feed.post", "Post", Post, Posted, Risk.WRITE, post, default_permissions=manage)
        )
        registrar.action(ActionSpec("feed.look", "Look", NoInput, NoInput, Risk.READ, look))
        registrar.action(
            ActionSpec("feed.clear", "Clear", Clear, NoInput, Risk.DESTRUCTIVE, clear, plan=clear_plan)
        )
        registrar.action(ActionSpec("feed.sulk", "Refuse", NoInput, NoInput, Risk.READ, sulk))
        registrar.action(ActionSpec("feed.crash", "Crash", NoInput, NoInput, Risk.READ, crash))
        registrar.action(
            ActionSpec("feed.slash", "Slash only", NoInput, NoInput, Risk.READ, look, surfaces=Surface.SLASH)
        )


@pytest.fixture
async def harness(teabot_harness: Any) -> PluginHarness:
    return await teabot_harness(Feed())


@pytest.fixture
async def client(harness: PluginHarness) -> AsyncIterator[httpx.AsyncClient]:
    health = Health("1", harness.pools.core_db(), lambda: {0: 0.05}, dict)
    app = build_app(health, tokens=harness.tokens, service=harness.registry)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8780") as client:
        yield client


async def token(harness: PluginHarness, member: int | None = None, **limits: Any) -> str:
    issued = await harness.tokens.issue(
        harness.guild.id, member or harness.member.id, NewToken("backend", **limits)
    )
    return issued.token


async def act(client: httpx.AsyncClient, bearer: str | None, name: str, body: Any = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {bearer}"} if bearer else {}
    content = json.dumps({"input": {}} if body is None else body)
    return await client.post(f"/api/v1/actions/{name}", headers=headers, content=content)


async def test_an_action_runs_as_the_tokens_member_and_returns_its_output(
    client: httpx.AsyncClient, harness: PluginHarness
) -> None:
    response = await act(client, await token(harness), "feed.post", {"input": {"text": "hello"}})
    assert (response.status_code, response.json()) == (200, {"output": {"text": "hello", "count": 1}})
    row = await harness.admin.fetchrow(
        "SELECT surface, token_id, outcome FROM core.audit_log WHERE action = 'feed.post'"
    )
    assert row is not None and (row["surface"], row["outcome"]) == ("service", "ok") and row["token_id"]


async def test_no_token_no_api(client: httpx.AsyncClient) -> None:
    assert (await act(client, None, "feed.look")).status_code == 401


async def test_an_input_key_is_optional_for_actions_without_input(
    client: httpx.AsyncClient, harness: PluginHarness
) -> None:
    assert (await act(client, await token(harness), "feed.look", {})).status_code == 200


@pytest.mark.parametrize("body", ["not json", [1, 2], {"input": [1]}, {"input": "x"}])
async def test_a_body_that_is_not_an_input_object_is_a_bad_request(
    client: httpx.AsyncClient, harness: PluginHarness, body: Any
) -> None:
    headers = {"Authorization": f"Bearer {await token(harness)}"}
    content = body if isinstance(body, str) else json.dumps(body)
    response = await client.post("/api/v1/actions/feed.look", headers=headers, content=content)
    assert response.status_code == 400
    assert response.json() == {
        "error": "bad_request",
        "message": 'The body must be a JSON object such as {"input": {...}}.',
    }


@pytest.mark.parametrize(
    ("name", "limits", "body", "status", "code"),
    [
        ("feed.nope", {}, None, 404, "unknown_action"),
        ("feed.slash", {}, None, 404, "wrong_surface"),
        ("tokens.create", {}, {"input": {"label": "x"}}, 404, "wrong_surface"),
        ("feed.post", {"max_risk": Risk.READ}, {"input": {"text": "x"}}, 403, "above_token_risk"),
        ("feed.post", {"allowed": ["feed.look"]}, {"input": {"text": "x"}}, 403, "not_allowed_by_token"),
        ("feed.post", {}, {"input": {}}, 422, "invalid_input"),
    ],
)
async def test_refusals_carry_a_status_and_a_code(
    client: httpx.AsyncClient,
    harness: PluginHarness,
    name: str,
    limits: dict[str, Any],
    body: Any,
    status: int,
    code: str,
) -> None:
    response = await act(client, await token(harness, **limits), name, body)
    assert (response.status_code, response.json()["error"]) == (status, code)


async def test_a_member_without_the_permission_is_forbidden(
    client: httpx.AsyncClient, harness: PluginHarness
) -> None:
    member = harness.guild.add_member(discord.Permissions.none())
    response = await act(client, await token(harness, member.id), "feed.post", {"input": {"text": "x"}})
    assert (response.status_code, response.json()["error"]) == (403, "forbidden")


async def test_a_plugin_disabled_here_is_a_conflict(
    client: httpx.AsyncClient, harness: PluginHarness
) -> None:
    await harness.invoke("plugins.disable", {"plugin": "feed"})
    response = await act(client, await token(harness), "feed.look")
    assert (response.status_code, response.json()["error"]) == (409, "plugin_not_enabled")


async def test_a_token_for_a_server_the_bot_is_not_in_is_a_conflict(
    client: httpx.AsyncClient, harness: PluginHarness
) -> None:
    issued = await harness.tokens.issue(424242, harness.member.id, NewToken("elsewhere"))
    response = await act(client, issued.token, "feed.look")
    assert (response.status_code, response.json()["error"]) == (409, "not_in_guild")


async def test_an_action_error_is_told_and_a_crash_is_not(
    client: httpx.AsyncClient, harness: PluginHarness
) -> None:
    bearer = await token(harness)
    sulked = await act(client, bearer, "feed.sulk")
    assert (sulked.status_code, sulked.json()) == (400, {"error": "action_error", "message": "Not today."})
    crashed = await act(client, bearer, "feed.crash")
    assert (crashed.status_code, crashed.json()) == (
        500,
        {"error": "action_failed", "message": "The action failed. Its audit row has the details."},
    )


async def test_only_post_is_served(client: httpx.AsyncClient, harness: PluginHarness) -> None:
    headers = {"Authorization": f"Bearer {await token(harness)}"}
    assert (await client.get("/api/v1/actions/feed.look", headers=headers)).status_code == 405


def test_every_refusal_code_has_a_status() -> None:
    assert set(STATUS) == set(get_args(RefusalCode.__value__))


async def test_a_destructive_action_plans_then_applies_over_the_api(
    client: httpx.AsyncClient, harness: PluginHarness
) -> None:
    bearer = await token(harness, max_risk=Risk.DESTRUCTIVE)
    plan = (await act(client, bearer, "feed.clear", {"input": {"prefix": "a"}})).json()["output"]
    assert (plan["counts"], plan["entries"][0]["target"]) == ({"remove": 1}, "apple")
    confirmed = await act(
        client, bearer, "feed.clear", {"input": {"prefix": "a", "confirm": plan["confirm"]}}
    )
    assert confirmed.status_code == 200 and confirmed.json()["output"]["job_id"]
    reused = await act(client, bearer, "feed.clear", {"input": {"prefix": "a", "confirm": plan["confirm"]}})
    assert (reused.status_code, reused.json()["error"]) == (409, "plan_used")


async def test_a_destructive_action_needs_a_token_that_allows_it(
    client: httpx.AsyncClient, harness: PluginHarness
) -> None:
    response = await act(client, await token(harness), "feed.clear", {"input": {"prefix": "a"}})
    assert (response.status_code, response.json()["error"]) == (403, "above_token_risk")
