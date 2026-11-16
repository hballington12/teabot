"""Signing in with Discord (OAuth 2): the member approves teabot reading who they are and which servers they are in.

The scopes are `identify` and `guilds`. teabot keeps no Discord token: it reads the member and their servers once,
at sign-in, and then forgets the token.
"""

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

AUTHORIZE = "https://discord.com/oauth2/authorize"
API = "https://discord.com/api/v10"
SCOPES = "identify guilds"
MANAGE_GUILD = 1 << 5
ADMINISTRATOR = 1 << 3


class SignInFailed(Exception):
    """Discord refused the sign-in, such as for an expired code."""


@dataclass(frozen=True)
class Member:
    """Who signed in, and the servers whose settings Discord says they may manage."""

    user_id: int
    name: str
    managed: list[int]


@dataclass(frozen=True)
class DiscordOAuth:
    """`client_id` is the bot's application ID; `secret` its OAuth2 client secret; `redirect_uri` the dashboard's
    callback, which the developer portal must list under OAuth2, Redirects."""

    client_id: int
    secret: str
    redirect_uri: str
    transport: httpx.AsyncBaseTransport | None = None

    def authorize_url(self, state: str) -> str:
        query = {
            "client_id": self.client_id,
            "response_type": "code",
            "redirect_uri": self.redirect_uri,
            "scope": SCOPES,
            "state": state,
        }
        return f"{AUTHORIZE}?{urlencode(query)}"

    async def member(self, code: str) -> Member:
        """Exchange the code Discord sent back for who signed in. Raises `SignInFailed`."""
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as client:
            reply = await client.post(
                f"{API}/oauth2/token",
                data={"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri},
                auth=(str(self.client_id), self.secret),
            )
            if reply.status_code != 200:
                raise SignInFailed(f"Discord refused the sign-in ({reply.status_code})")
            headers = {"Authorization": f"Bearer {reply.json()['access_token']}"}
            me = (await client.get(f"{API}/users/@me", headers=headers)).json()
            guilds = (await client.get(f"{API}/users/@me/guilds", headers=headers)).json()
        managed = [
            int(g["id"]) for g in guilds if int(g.get("permissions", 0)) & (MANAGE_GUILD | ADMINISTRATOR)
        ]
        return Member(int(me["id"]), str(me.get("global_name") or me["username"]), managed)
