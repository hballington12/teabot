"""The site's routes (D53): the home page, the plugin browser, sign-in with Discord, choosing a server, and turning
its plugins on and off or changing their settings in place.

Every change goes through the registry as the signed-in member, through the `web` door, so it checks their live
Discord permissions, as `/plugins` does, and the audit log records it. Each form carries the session's own token,
so another site cannot submit one in the member's name. A change sent by the page's script is answered in JSON,
which the page shows in place; without the script, the form posts and the page reloads with a note.
"""

import json
import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import BaseRoute, Route

from teabot import catalogue
from teabot.catalogue import Listed
from teabot.core.registry import ActionFailed, Call, Refused, Registry
from teabot.sdk import Actor, Manifest
from teabot.site import pages
from teabot.site.info import PluginInfo, installed
from teabot.site.layout import Frame, Viewer, note
from teabot.site.oauth import DiscordOAuth, SignInFailed
from teabot.site.sessions import LIFETIME, Session, Sessions

SESSION_COOKIE = "teabot_session"
STATE_COOKIE = "teabot_oauth_state"
NEXT_COOKIE = "teabot_next"
SERVER_COOKIE = "teabot_server"
NOTE_COOKIE = "teabot_note"
CATALOGUE_SECONDS = 3600
LEGAL = ("privacy", "terms")
STATIC = Path(__file__).parent / "static"
STATIC_FILES = {"site.css", "site.js", "logo.png", "favicon.png"}
INVITE = "https://discord.com/oauth2/authorize?client_id={}&scope=bot+applications.commands&permissions=8"


def safe_next(path: str | None) -> str:
    """A path on this site to return to, never another site's address."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/plugins"
    return path


class Change(BaseModel):
    """What a change did: whether it worked, what to tell the member, and the plugin's state after it."""

    ok: bool
    message: str
    state: str | None = None


@dataclass
class Site:
    """`client` is the Discord client, for the instance's name and the servers it is in. `manifests` are the loaded
    plugins'. `oauth` is None when the operator has not given the OAuth2 client secret, and nobody can sign in.
    `pages_dir` holds the operator's `privacy.md` and `terms.md`. `secure` marks the cookies HTTPS-only."""

    registry: Registry
    sessions: Sessions
    oauth: DiscordOAuth | None
    client: Any
    manifests: Mapping[str, Manifest]
    client_id: int | None
    secure: bool
    pages_dir: Path = Path("pages")
    hub_url: str = catalogue.DEFAULT_HUB
    _listed: dict[str, Listed] = field(default_factory=dict[str, Listed])
    _listed_at: float = 0.0

    def routes(self) -> list[BaseRoute]:
        return [
            Route("/", self.home),
            Route("/plugins", self.plugins),
            Route("/plugins.json", self.plugins_json),
            Route("/plugins/{plugin}", self.plugin),
            Route("/plugins/{plugin}/{verb}", self.change, methods=["POST"]),
            Route("/server", self.choose_server, methods=["POST"]),
            Route("/login", self.login),
            Route("/auth/callback", self.callback),
            Route("/logout", self.logout, methods=["POST"]),
            Route("/privacy", self.legal),
            Route("/terms", self.legal),
            Route("/static/{name}", self.static),
            Route("/dashboard", self.moved),
            Route("/dashboard/{rest:path}", self.moved),
        ]

    # What every page needs.

    async def _session(self, request: Request) -> Session | None:
        return await self.sessions.find(request.cookies.get(SESSION_COOKIE))

    def _servers(self, session: Session) -> list[tuple[int, str]]:
        found = [
            (gid, str(g.name)) for gid in session.guild_ids if (g := self.client.get_guild(gid)) is not None
        ]
        return sorted(found, key=lambda f: f[1].lower())

    def _chosen(
        self, request: Request, session: Session | None, servers: list[tuple[int, str]]
    ) -> int | None:
        raw = request.cookies.get(SERVER_COOKIE, "")
        wanted = int(raw) if raw.isdigit() else None
        if session is None or wanted not in {gid for gid, _ in servers}:
            return None
        return wanted

    async def _frame(self, request: Request) -> tuple[Frame, Session | None]:
        session = await self._session(request)
        viewer = Viewer()
        if session is not None:
            servers = self._servers(session)
            viewer = Viewer(session.name, session.csrf, servers, self._chosen(request, session, servers))
        me = getattr(self.client, "user", None)
        avatar = getattr(getattr(me, "display_avatar", None), "url", None)
        legal = tuple(name for name in LEGAL if (self.pages_dir / f"{name}.md").is_file())
        frame = Frame(
            str(getattr(me, "name", None) or "teabot"),
            str(avatar) if avatar else None,
            self.oauth is not None,
            viewer,
            request.url.path,
            legal,
        )
        return frame, session

    async def _hub(self) -> dict[str, Listed]:
        """The hub's catalogue, read at most hourly, for what each plugin contacts."""
        if time.monotonic() - self._listed_at > CATALOGUE_SECONDS:
            try:
                self._listed = await catalogue.fetch_async(self.hub_url)
            except Exception:  # The site still works without the hub.
                self._listed = self._listed or {}
            self._listed_at = time.monotonic()
        return self._listed

    async def _installed(self) -> list[PluginInfo]:
        return installed(self.manifests, await self._hub())

    async def _invoke(
        self, session: Session, guild_id: int, action: str, raw: Mapping[str, Any]
    ) -> BaseModel:
        return await self.registry.invoke(Call(action, guild_id, Actor(session.user_id, "web"), raw))

    def _flash(self, request: Request) -> str:
        raw = request.cookies.get(NOTE_COOKIE)
        if not raw:
            return ""
        try:
            sent = json.loads(raw)
            return note(str(sent["text"]), bad=bool(sent.get("bad")))
        except (ValueError, KeyError, TypeError):
            return ""

    def _html(self, html: str, request: Request, status: int = 200) -> HTMLResponse:
        response = HTMLResponse(html, status)
        if NOTE_COOKIE in request.cookies:
            response.delete_cookie(NOTE_COOKIE)
        return response

    # Pages.

    async def home(self, request: Request) -> Response:
        frame, _ = await self._frame(request)
        invite = INVITE.format(self.client_id) if self.client_id is not None else None
        return self._html(pages.home(frame, invite, await self._installed()), request)

    async def _states(self, frame: Frame, session: Session | None) -> tuple[dict[str, pages.Here], str]:
        """Each plugin's state in the chosen server, or why the member cannot see them."""
        chosen = frame.viewer.chosen
        if session is None or chosen is None:
            return {}, ""
        try:
            listed = (await self._invoke(session, chosen, "plugins.list", {})).model_dump()["plugins"]
        except Refused as refusal:
            return {}, note(refusal.message, bad=True)
        return {str(p["plugin"]): pages.Here(str(p["state"])) for p in listed}, ""

    async def plugins(self, request: Request) -> Response:
        frame, session = await self._frame(request)
        here, refused = await self._states(frame, session)
        status = self._flash(request) or refused
        return self._html(pages.plugins(frame, await self._installed(), here, status), request)

    async def plugin(self, request: Request) -> Response:
        frame, session = await self._frame(request)
        wanted = str(request.path_params["plugin"])
        found = next((p for p in await self._installed() if p.id == wanted), None)
        if found is None:
            return self._html(
                pages.problem(frame, "Not found", "This teabot runs no plugin by that name."), request, 404
            )
        states, refused = await self._states(frame, session)
        here = states.get(wanted)
        if here is not None and here.switchable and session is not None and frame.viewer.chosen is not None:
            config = await self._invoke(session, frame.viewer.chosen, "plugins.config", {"plugin": wanted})
            here = pages.Here(here.state, dict(config.model_dump()["settings"]))
        status = self._flash(request) or refused
        return self._html(pages.plugin_page(frame, found, here, status), request)

    async def plugins_json(self, request: Request) -> Response:
        found = [p.summary() for p in await self._installed()]
        return JSONResponse({"plugins": found}, headers={"Access-Control-Allow-Origin": "*"})

    async def legal(self, request: Request) -> Response:
        name = request.url.path.strip("/")
        file = self.pages_dir / f"{name}.md"
        frame, _ = await self._frame(request)
        if name not in LEGAL or not file.is_file():
            return self._html(
                pages.problem(frame, "Not found", "This teabot has no such page."), request, 404
            )
        title = "Privacy policy" if name == "privacy" else "Terms of service"
        return self._html(pages.legal(frame, title, file.read_text()), request)

    async def static(self, request: Request) -> Response:
        name = str(request.path_params["name"])
        if name not in STATIC_FILES:
            return Response(status_code=404)
        return FileResponse(STATIC / name, headers={"Cache-Control": "public, max-age=3600"})

    async def moved(self, request: Request) -> Response:
        """The dashboard's old addresses, which the plugin browser replaced."""
        return RedirectResponse("/plugins", status_code=301)

    # Signing in and out, and choosing a server.

    def _cookie(self, response: Response, name: str, value: str, max_age: int) -> None:
        response.set_cookie(name, value, max_age=max_age, httponly=True, secure=self.secure, samesite="lax")

    async def login(self, request: Request) -> Response:
        if self.oauth is None:
            return RedirectResponse("/", status_code=303)
        state = secrets.token_urlsafe(24)
        response = RedirectResponse(self.oauth.authorize_url(state), status_code=303)
        self._cookie(response, STATE_COOKIE, state, 600)
        self._cookie(response, NEXT_COOKIE, safe_next(request.query_params.get("next")), 600)
        return response

    async def callback(self, request: Request) -> Response:
        state, code = request.query_params.get("state"), request.query_params.get("code")
        expected = request.cookies.get(STATE_COOKIE)
        frame, _ = await self._frame(request)
        if (
            self.oauth is None
            or not code
            or not state
            or not expected
            or not secrets.compare_digest(state, expected)
        ):
            return self._html(
                pages.problem(frame, "Sign-in failed", "That sign-in expired. Try again."), request, 400
            )
        try:
            member = await self.oauth.member(code)
        except SignInFailed as exc:
            return self._html(pages.problem(frame, "Sign-in failed", str(exc)), request, 400)
        token = await self.sessions.start(member.user_id, member.name, member.managed)
        response = RedirectResponse(safe_next(request.cookies.get(NEXT_COOKIE)), status_code=303)
        response.delete_cookie(STATE_COOKIE)
        response.delete_cookie(NEXT_COOKIE)
        self._cookie(response, SESSION_COOKIE, token, int(LIFETIME.total_seconds()))
        return response

    async def _form_ok(self, request: Request, session: Session) -> bool:
        sent = str((await request.form()).get("csrf", ""))
        return secrets.compare_digest(sent, session.csrf)

    async def logout(self, request: Request) -> Response:
        session = await self._session(request)
        if session is not None and await self._form_ok(request, session):
            await self.sessions.end(request.cookies.get(SESSION_COOKIE))
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(SESSION_COOKIE)
        response.delete_cookie(SERVER_COOKIE)
        return response

    async def choose_server(self, request: Request) -> Response:
        session = await self._session(request)
        form = await request.form()
        response = RedirectResponse(safe_next(str(form.get("next", ""))), status_code=303)
        if session is None or not await self._form_ok(request, session):
            return response
        wanted = str(form.get("guild", ""))
        if wanted.isdigit() and int(wanted) in session.guild_ids:
            self._cookie(response, SERVER_COOKIE, wanted, int(LIFETIME.total_seconds()))
        else:
            response.delete_cookie(SERVER_COOKIE)
        return response

    # Changing a plugin.

    async def change(self, request: Request) -> Response:
        session = await self._session(request)
        plugin, verb = str(request.path_params["plugin"]), str(request.path_params["verb"])
        form = await request.form()
        guild = str(form.get("guild", ""))
        if session is None or not await self._form_ok(request, session):
            done = Change(ok=False, message="Your sign-in has expired. Sign in again.")
        elif not guild.isdigit() or int(guild) not in session.guild_ids:
            done = Change(ok=False, message="Choose one of your servers first.")
        else:
            done = await self._apply(session, int(guild), plugin, verb, form)
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse(done.model_dump(), status_code=200 if done.ok else 400)
        response = RedirectResponse(f"/plugins/{quote(plugin)}", status_code=303)
        self._cookie(response, NOTE_COOKIE, json.dumps({"text": done.message, "bad": not done.ok}), 60)
        return response

    async def _apply(self, session: Session, guild_id: int, plugin: str, verb: str, form: Any) -> Change:
        try:
            if verb in ("enable", "disable"):
                await self._invoke(session, guild_id, f"plugins.{verb}", {"plugin": plugin})
                state = "enabled" if verb == "enable" else "disabled"
                return Change(
                    ok=True, message=f"{plugin} is now {'on' if verb == 'enable' else 'off'}.", state=state
                )
            if verb != "settings":
                return Change(ok=False, message="There is nothing to do there.")
            changed = await self._save_settings(session, guild_id, plugin, form)
            message = (
                f"Saved {changed} setting{'s' if changed != 1 else ''}." if changed else "Nothing changed."
            )
            return Change(ok=True, message=message)
        except Refused as refusal:
            return Change(ok=False, message=refusal.message)
        except ActionFailed as failure:
            return Change(ok=False, message=failure.public_message or "That did not work.")

    async def _save_settings(self, session: Session, guild_id: int, plugin: str, form: Any) -> int:
        current = (await self._invoke(session, guild_id, "plugins.config", {"plugin": plugin})).model_dump()
        changed = 0
        for name, value in current["settings"].items():
            sent = form.get(name)
            shown = value if isinstance(value, str) else json.dumps(value)
            if sent is not None and str(sent) != shown:
                await self._invoke(
                    session,
                    guild_id,
                    "plugins.config",
                    {"plugin": plugin, "setting": name, "value": str(sent)},
                )
                changed += 1
        return changed
