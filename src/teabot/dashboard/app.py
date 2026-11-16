"""The dashboard's routes (D51): sign in with Discord, pick a server, and turn its plugins on and off or change
their settings.

Every change goes through the registry as the signed-in member, through the `web` door, so it checks their live
Discord permissions, as `/plugins` does, and the audit log records it. Each form carries the session's own token,
so another site cannot submit one in the member's name.
"""

import json
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Route

from teabot import catalogue
from teabot.catalogue import Listed
from teabot.core.registry import ActionFailed, Call, Refused, Registry
from teabot.dashboard import pages
from teabot.dashboard.oauth import DiscordOAuth, SignInFailed
from teabot.dashboard.sessions import LIFETIME, Session, Sessions
from teabot.sdk import Actor

SESSION_COOKIE = "teabot_session"
STATE_COOKIE = "teabot_oauth_state"
CATALOGUE_SECONDS = 3600
LOADED = ("enabled", "disabled")


@dataclass
class Dashboard:
    """`client` is the Discord client, for the servers' names and whether the bot is in them. `secure` marks the
    cookies HTTPS-only, as they should be whenever the dashboard is served over HTTPS."""

    registry: Registry
    sessions: Sessions
    oauth: DiscordOAuth
    client: Any
    secure: bool
    hub_url: str = catalogue.DEFAULT_HUB
    _listed: dict[str, Listed] = field(default_factory=dict[str, Listed])
    _listed_at: float = 0.0

    def routes(self) -> list[BaseRoute]:
        return [
            Route("/dashboard", self.index),
            Route("/dashboard/login", self.login),
            Route("/dashboard/callback", self.callback),
            Route("/dashboard/logout", self.logout, methods=["POST"]),
            Route("/dashboard/{guild_id:int}", self.guild),
            Route("/dashboard/{guild_id:int}/{plugin}/{verb}", self.change, methods=["POST"]),
        ]

    async def _session(self, request: Request) -> Session | None:
        return await self.sessions.find(request.cookies.get(SESSION_COOKIE))

    async def index(self, request: Request) -> Response:
        session = await self._session(request)
        if session is None:
            return HTMLResponse(pages.sign_in())
        found = [(gid, str(g.name)) for gid in sorted(session.guild_ids) if (g := self.client.get_guild(gid))]
        return HTMLResponse(
            pages.servers(session.name, session.csrf, sorted(found, key=lambda f: f[1].lower()))
        )

    async def login(self, request: Request) -> Response:
        state = secrets.token_urlsafe(24)
        response = RedirectResponse(self.oauth.authorize_url(state), status_code=303)
        response.set_cookie(
            STATE_COOKIE, state, max_age=600, httponly=True, secure=self.secure, samesite="lax"
        )
        return response

    async def callback(self, request: Request) -> Response:
        state, code = request.query_params.get("state"), request.query_params.get("code")
        expected = request.cookies.get(STATE_COOKIE)
        if not code or not state or not expected or not secrets.compare_digest(state, expected):
            return HTMLResponse(
                pages.page("Sign-in failed", pages.message("That sign-in expired. Try again.", bad=True)), 400
            )
        try:
            member = await self.oauth.member(code)
        except SignInFailed as exc:
            return HTMLResponse(pages.page("Sign-in failed", pages.message(str(exc), bad=True)), 400)
        token = await self.sessions.start(member.user_id, member.name, member.managed)
        response = RedirectResponse("/dashboard", status_code=303)
        response.delete_cookie(STATE_COOKIE)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=int(LIFETIME.total_seconds()),
            httponly=True,
            secure=self.secure,
            samesite="lax",
        )
        return response

    async def logout(self, request: Request) -> Response:
        session = await self._session(request)
        if session is not None and await self._form_ok(request, session):
            await self.sessions.end(request.cookies.get(SESSION_COOKIE))
        response = RedirectResponse("/dashboard", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        return response

    async def _form_ok(self, request: Request, session: Session) -> bool:
        sent = str((await request.form()).get("csrf", ""))
        return secrets.compare_digest(sent, session.csrf)

    async def _hub(self) -> dict[str, Listed]:
        """The hub's catalogue, read at most hourly, for what each plugin does and contacts."""
        if time.monotonic() - self._listed_at > CATALOGUE_SECONDS:
            try:
                self._listed = await catalogue.fetch_async(self.hub_url)
            except Exception:  # The page still works without the hub's descriptions.
                self._listed = self._listed or {}
            self._listed_at = time.monotonic()
        return self._listed

    async def _invoke(
        self, session: Session, guild_id: int, action: str, raw: Mapping[str, Any]
    ) -> BaseModel:
        return await self.registry.invoke(Call(action, guild_id, Actor(session.user_id, "web"), raw))

    async def _rows(self, session: Session, guild_id: int) -> list[pages.PluginRow]:
        states = (await self._invoke(session, guild_id, "plugins.list", {})).model_dump()["plugins"]
        listed = await self._hub()
        rows: list[pages.PluginRow] = []
        for state in states:
            plugin_id, label = str(state["plugin"]), str(state["state"])
            settings = None
            if label in LOADED:
                found = await self._invoke(session, guild_id, "plugins.config", {"plugin": plugin_id})
                settings = dict(found.model_dump()["settings"])
            hub = listed.get(plugin_id)
            chosen = hub.for_teabot() if hub is not None else None
            rows.append(
                pages.PluginRow(
                    plugin_id,
                    label,
                    hub.description if hub is not None else "",
                    chosen.external_connections if chosen is not None else "",
                    settings,
                )
            )
        return rows

    async def guild(self, request: Request) -> Response:
        session = await self._session(request)
        guild_id = int(request.path_params["guild_id"])
        found = self.client.get_guild(guild_id)
        if session is None or guild_id not in session.guild_ids or found is None:
            return RedirectResponse("/dashboard", status_code=303)
        try:
            rows = await self._rows(session, guild_id)
        except Refused as refusal:
            body = pages.message(refusal.message, bad=True)
            return HTMLResponse(
                pages.page(str(found.name), body, signed_in=session.name, csrf=session.csrf), 403
            )
        note = request.query_params.get("note")
        bad = request.query_params.get("bad") == "1"
        shown = pages.GuildPage(
            session.name, session.csrf, guild_id, str(found.name), tuple(rows), note or "", bad
        )
        return HTMLResponse(pages.guild(shown))

    async def change(self, request: Request) -> Response:
        session = await self._session(request)
        guild_id = int(request.path_params["guild_id"])
        plugin, verb = str(request.path_params["plugin"]), str(request.path_params["verb"])
        if session is None or guild_id not in session.guild_ids or not await self._form_ok(request, session):
            return RedirectResponse("/dashboard", status_code=303)
        try:
            note = await self._apply(session, guild_id, plugin, verb, await request.form())
            bad = False
        except Refused as refusal:
            note, bad = refusal.message, True
        except ActionFailed as failure:
            note, bad = failure.public_message or "That did not work.", True
        query = urlencode({"note": note, **({"bad": "1"} if bad else {})})
        return RedirectResponse(f"/dashboard/{guild_id}?{query}#{plugin}", status_code=303)

    async def _apply(self, session: Session, guild_id: int, plugin: str, verb: str, form: Any) -> str:
        if verb in ("enable", "disable"):
            await self._invoke(session, guild_id, f"plugins.{verb}", {"plugin": plugin})
            return f"{plugin} is now {verb}d here."
        if verb != "settings":
            raise Refused("unknown_action", "There is nothing to do there.")
        current = (await self._invoke(session, guild_id, "plugins.config", {"plugin": plugin})).model_dump()[
            "settings"
        ]
        changed = 0
        for name, value in current.items():
            sent = form.get(name)
            shown = value if isinstance(value, str) else json.dumps(value)
            if sent is not None and str(sent) != shown:
                raw = {"plugin": plugin, "setting": name, "value": str(sent)}
                await self._invoke(session, guild_id, "plugins.config", raw)
                changed += 1
        return (
            f"Saved {changed} setting{'s' if changed != 1 else ''} of {plugin}."
            if changed
            else "Nothing changed."
        )
