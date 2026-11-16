"""The dashboard: signing in with Discord, then turning a plugin on and off and changing its settings, through
the same checks as /plugins."""

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

import discord
import httpx
import pytest
from pydantic import BaseModel
from starlette.applications import Starlette

from teabot import catalogue
from teabot.dashboard.app import SESSION_COOKIE, Dashboard
from teabot.dashboard.oauth import DiscordOAuth
from teabot.dashboard.sessions import Sessions
from teabot.sdk import Context, Plugin
from teabot.testing import HarnessFactory, PluginHarness


class Cfg(BaseModel):
    greeting: str = "hi"
    times: int = 1


plugin = Plugin("hello", config=Cfg)


@plugin.action()
async def wave(ctx: Context[Cfg]) -> str:
    """Wave."""
    return ctx.config.greeting * ctx.config.times


def fake_discord(user_id: int, managed: list[int]) -> httpx.MockTransport:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth2/token"):
            return httpx.Response(200, json={"access_token": "t"})
        if request.url.path.endswith("/users/@me"):
            return httpx.Response(200, json={"id": str(user_id), "username": "sam", "global_name": "Sam"})
        return httpx.Response(200, json=[{"id": str(g), "permissions": "32"} for g in managed])

    return httpx.MockTransport(answer)


@pytest.fixture
async def harness(teabot_harness: HarnessFactory, monkeypatch: pytest.MonkeyPatch) -> PluginHarness:
    async def no_hub(url: str = "", transport: Any = None) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(catalogue, "fetch_async", no_hub)
    return await teabot_harness(plugin)


def site(
    harness: PluginHarness, managed: list[int] | None = None, user: int | None = None
) -> httpx.AsyncClient:
    guilds = managed if managed is not None else [harness.guild.id]
    oauth = DiscordOAuth(
        1, "secret", "http://bot.test/dashboard/callback", fake_discord(user or harness.member.id, guilds)
    )
    dash = Dashboard(harness.registry, Sessions(harness.pools.core_db()), oauth, harness.client, secure=False)
    app = Starlette(routes=dash.routes())
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bot.test")


async def signed_in(web: httpx.AsyncClient) -> None:
    login = await web.get("/dashboard/login")
    state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
    back = await web.get("/dashboard/callback", params={"code": "c", "state": state})
    assert back.status_code == 303 and SESSION_COOKIE in back.cookies


def csrf(html: str) -> str:
    found = re.search(r'name="csrf" value="([^"]+)"', html)
    assert found is not None
    return found.group(1)


async def enabled(harness: PluginHarness) -> bool:
    return bool(
        await harness.admin.fetchval(
            "SELECT enabled FROM core.guild_plugins WHERE guild_id = $1 AND plugin_id = 'hello'",
            harness.guild.id,
        )
    )


async def test_signing_in_lists_the_servers_the_member_manages(harness: PluginHarness) -> None:
    harness.guild.name = "Tea"
    async with site(harness) as web:
        assert "Sign in with Discord" in (await web.get("/dashboard")).text
        await signed_in(web)
        listed = (await web.get("/dashboard")).text
        assert f'href="/dashboard/{harness.guild.id}">Tea<' in listed


async def test_a_sign_in_with_the_wrong_state_is_refused(harness: PluginHarness) -> None:
    async with site(harness) as web:
        await web.get("/dashboard/login")
        back = await web.get("/dashboard/callback", params={"code": "c", "state": "forged"})
        assert back.status_code == 400 and SESSION_COOKIE not in back.cookies


async def test_a_plugin_is_turned_off_and_its_settings_changed(harness: PluginHarness) -> None:
    async with site(harness) as web:
        await signed_in(web)
        page = (await web.get(f"/dashboard/{harness.guild.id}")).text
        assert 'id="hello"' in page and 'value="hi"' in page
        token = csrf(page)
        off = await web.post(f"/dashboard/{harness.guild.id}/hello/disable", data={"csrf": token})
        assert "hello+is+now+disabled+here" in off.headers["location"]
        assert not await enabled(harness)
        await web.post(f"/dashboard/{harness.guild.id}/hello/enable", data={"csrf": token})
        saved = await web.post(
            f"/dashboard/{harness.guild.id}/hello/settings",
            data={"csrf": token, "greeting": "yo", "times": "2"},
        )
        assert "Saved+2+settings" in saved.headers["location"]
        assert await harness.call(wave) == "yoyo"


async def test_a_form_without_the_sessions_token_changes_nothing(harness: PluginHarness) -> None:
    async with site(harness) as web:
        await signed_in(web)
        await web.post(f"/dashboard/{harness.guild.id}/hello/disable", data={"csrf": "forged"})
        assert await enabled(harness)


async def test_a_member_without_manage_server_cannot_change_plugins(harness: PluginHarness) -> None:
    member = harness.guild.add_member(discord.Permissions.none())
    async with site(harness, user=member.id) as web:
        await signed_in(web)
        page = await web.get(f"/dashboard/{harness.guild.id}")
        assert page.status_code == 403 and "needs permissions you do not have" in page.text
        await web.post(f"/dashboard/{harness.guild.id}/hello/disable", data={"csrf": "x"})
        assert await enabled(harness)


async def test_a_server_the_member_does_not_manage_is_not_shown(harness: PluginHarness) -> None:
    async with site(harness, managed=[]) as web:
        await signed_in(web)
        assert (await web.get(f"/dashboard/{harness.guild.id}")).status_code == 303
