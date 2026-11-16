"""The instance's site: its home page and plugin browser, signing in with Discord, choosing a server, and turning a
plugin on and off or changing its settings in place, through the same checks as /plugins."""

import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import discord
import httpx
import pytest
from pydantic import BaseModel
from starlette.applications import Starlette

from teabot import catalogue
from teabot.sdk import Context, Plugin
from teabot.site.app import SESSION_COOKIE, Site, safe_next
from teabot.site.oauth import DiscordOAuth
from teabot.site.sessions import Sessions
from teabot.testing import HarnessFactory, PluginHarness


class Cfg(BaseModel):
    greeting: str = "hi"
    times: int = 1


plugin = Plugin("hello", config=Cfg, description="Says hello <loudly>.")
JSON = {"Accept": "application/json"}


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
    harness = await teabot_harness(plugin)
    harness.guild.name = "Tea"
    return harness


def site(
    harness: PluginHarness,
    managed: list[int] | None = None,
    user: int | None = None,
    *,
    sign_in: bool = True,
    pages_dir: Path = Path("no-pages-here"),
) -> httpx.AsyncClient:
    guilds = managed if managed is not None else [harness.guild.id]
    oauth = DiscordOAuth(
        1, "secret", "http://bot.test/auth/callback", fake_discord(user or harness.member.id, guilds)
    )
    built = Site(
        harness.registry,
        Sessions(harness.pools.core_db()),
        oauth if sign_in else None,
        harness.client,
        {"hello": plugin.manifest},
        1234,
        secure=False,
        pages_dir=pages_dir,
    )
    app = Starlette(routes=built.routes())
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://bot.test")


async def sign_in(web: httpx.AsyncClient, back_to: str = "/plugins") -> httpx.Response:
    login = await web.get("/login", params={"next": back_to})
    state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
    back = await web.get("/auth/callback", params={"code": "c", "state": state})
    assert back.status_code == 303 and SESSION_COOKIE in back.cookies
    return back


def csrf(html: str) -> str:
    found = re.search(r'name="csrf" value="([^"]+)"', html)
    assert found is not None
    return found.group(1)


async def choose(web: httpx.AsyncClient, guild_id: int) -> None:
    token = csrf((await web.get("/plugins")).text)
    await web.post("/server", data={"csrf": token, "guild": str(guild_id), "next": "/plugins"})


async def enabled(harness: PluginHarness) -> bool:
    return bool(
        await harness.admin.fetchval(
            "SELECT enabled FROM core.guild_plugins WHERE guild_id = $1 AND plugin_id = 'hello'",
            harness.guild.id,
        )
    )


async def test_anyone_sees_the_home_page_and_the_plugins(harness: PluginHarness) -> None:
    async with site(harness) as web:
        home = (await web.get("/")).text
        assert "client_id=1234" in home and 'href="/plugins/hello"' in home
        browser = (await web.get("/plugins")).text
        assert "Says hello &lt;loudly&gt;." in browser and "Sign in with Discord" in browser
        assert "data-enhance" not in browser
        listed = (await web.get("/plugins.json")).json()
        assert listed["plugins"][0]["id"] == "hello"
        assert listed["plugins"][0]["description"] == "Says hello <loudly>."


async def test_signing_in_returns_to_the_page_and_offers_the_members_servers(harness: PluginHarness) -> None:
    async with site(harness) as web:
        back = await sign_in(web, "/plugins/hello")
        assert back.headers["location"] == "/plugins/hello"
        page = (await web.get("/plugins/hello")).text
        assert f'<option value="{harness.guild.id}">Tea</option>' in page
        assert "Choose a server" in page


async def test_a_sign_in_never_returns_to_another_site(harness: PluginHarness) -> None:
    assert [safe_next(p) for p in ("//evil.test", "https://evil.test", "/\\evil", "", "/plugins/x")] == [
        "/plugins",
        "/plugins",
        "/plugins",
        "/plugins",
        "/plugins/x",
    ]


async def test_a_sign_in_with_the_wrong_state_is_refused(harness: PluginHarness) -> None:
    async with site(harness) as web:
        await web.get("/login")
        back = await web.get("/auth/callback", params={"code": "c", "state": "forged"})
        assert back.status_code == 400 and SESSION_COOKIE not in back.cookies


async def test_a_plugin_is_switched_and_configured_in_place(harness: PluginHarness) -> None:
    async with site(harness) as web:
        await sign_in(web)
        await choose(web, harness.guild.id)
        page = (await web.get("/plugins/hello")).text
        assert 'aria-pressed="true"' in page and 'value="hi"' in page
        token = csrf(page)
        guild = str(harness.guild.id)
        off = await web.post("/plugins/hello/disable", data={"csrf": token, "guild": guild}, headers=JSON)
        assert off.json() == {"ok": True, "message": "hello is now off.", "state": "disabled"}
        assert not await enabled(harness)
        await web.post("/plugins/hello/enable", data={"csrf": token, "guild": guild}, headers=JSON)
        saved = await web.post(
            "/plugins/hello/settings",
            data={"csrf": token, "guild": guild, "greeting": "yo", "times": "2"},
            headers=JSON,
        )
        assert saved.json()["message"] == "Saved 2 settings."
        assert await harness.call(wave) == "yoyo"


async def test_without_the_script_a_change_reloads_the_page_with_a_note(harness: PluginHarness) -> None:
    async with site(harness) as web:
        await sign_in(web)
        await choose(web, harness.guild.id)
        token = csrf((await web.get("/plugins")).text)
        off = await web.post("/plugins/hello/disable", data={"csrf": token, "guild": str(harness.guild.id)})
        assert off.status_code == 303 and off.headers["location"] == "/plugins/hello"
        assert "hello is now off." in (await web.get("/plugins/hello")).text
        assert "hello is now off." not in (await web.get("/plugins/hello")).text


async def test_a_form_without_the_sessions_token_changes_nothing(harness: PluginHarness) -> None:
    async with site(harness) as web:
        await sign_in(web)
        forged = {"csrf": "forged", "guild": str(harness.guild.id)}
        refused = await web.post("/plugins/hello/disable", data=forged, headers=JSON)
        assert refused.status_code == 400 and not refused.json()["ok"]
        assert await enabled(harness)


async def test_a_member_without_manage_server_cannot_change_plugins(harness: PluginHarness) -> None:
    member = harness.guild.add_member(discord.Permissions.none())
    async with site(harness, user=member.id) as web:
        await sign_in(web)
        await choose(web, harness.guild.id)
        page = (await web.get("/plugins")).text
        assert "needs permissions you do not have" in page and "data-enhance" not in page
        token = csrf(page)
        refused = await web.post(
            "/plugins/hello/disable", data={"csrf": token, "guild": str(harness.guild.id)}, headers=JSON
        )
        assert not refused.json()["ok"]
        assert await enabled(harness)


async def test_a_server_the_member_does_not_manage_cannot_be_chosen(harness: PluginHarness) -> None:
    async with site(harness, managed=[]) as web:
        await sign_in(web)
        await choose(web, harness.guild.id)
        page = (await web.get("/plugins")).text
        assert "No servers to manage" in page and "data-enhance" not in page


async def test_the_operators_pages_show_when_they_exist_without_raw_html(
    harness: PluginHarness, tmp_path: Path
) -> None:
    (tmp_path / "privacy.md").write_text("# Privacy\n\nWe keep *little*. <script>alert(1)</script>\n")
    async with site(harness, pages_dir=tmp_path) as web:
        privacy = await web.get("/privacy")
        assert privacy.status_code == 200 and "<em>little</em>" in privacy.text
        assert "<script>alert" not in privacy.text
        assert (await web.get("/terms")).status_code == 404
        assert 'href="/privacy"' in (await web.get("/")).text
        assert 'href="/terms"' not in (await web.get("/")).text


async def test_the_old_dashboard_addresses_lead_to_the_plugins(harness: PluginHarness) -> None:
    async with site(harness) as web:
        for old in ("/dashboard", f"/dashboard/{harness.guild.id}"):
            moved = await web.get(old)
            assert moved.status_code == 301 and moved.headers["location"] == "/plugins"


async def test_without_sign_in_the_site_says_to_use_discord(harness: PluginHarness) -> None:
    async with site(harness, sign_in=False) as web:
        page = (await web.get("/plugins")).text
        assert "Sign in with Discord" not in page and "/plugins enable" in page
        assert (await web.get("/login")).headers["location"] == "/"


async def test_only_the_sites_own_files_are_served(harness: PluginHarness) -> None:
    async with site(harness) as web:
        assert (await web.get("/static/site.css")).status_code == 200
        assert (await web.get("/static/app.py")).status_code == 404
        assert (await web.get("/plugins/nothing")).status_code == 404
