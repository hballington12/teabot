"""The bearer-token check for `/mcp` and `/api` (D16, D28).

A plain ASGI middleware: a request under a guarded prefix needs `Authorization: Bearer teapot_...`. Without a
good token it gets 401 with a `WWW-Authenticate` challenge; with one, the token's `Grant` rides in the ASGI
scope for the adapter. Every other path passes untouched.
"""

import json
from collections.abc import Sequence

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from teapot.auth.tokens import Grant, TokenRefused, Tokens

SCOPE_KEY = "teapot.grant"


def grant_of(request: Request) -> Grant:
    """The grant the middleware checked for this request."""
    grant = request.scope.get(SCOPE_KEY)
    if not isinstance(grant, Grant):
        raise RuntimeError("route is not behind BearerTokens")
    return grant


def guarded(path: str, prefixes: Sequence[str]) -> bool:
    return any(path == p or path.startswith(p + "/") for p in prefixes)


class BearerTokens:
    def __init__(self, app: ASGIApp, tokens: Tokens, *, prefixes: Sequence[str]) -> None:
        self.app = app
        self.tokens = tokens
        self.prefixes = tuple(prefixes)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not guarded(scope["path"], self.prefixes):
            await self.app(scope, receive, send)
            return
        try:
            grant = await self.tokens.check(self._presented(scope))
        except TokenRefused as refusal:
            await self._refuse(send, str(refusal))
            return
        await self.app({**scope, SCOPE_KEY: grant}, receive, send)

    @staticmethod
    def _presented(scope: Scope) -> str:
        header = Request(scope).headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise TokenRefused("a bearer token is required")
        return token.strip()

    @staticmethod
    async def _refuse(send: Send, reason: str) -> None:
        body = json.dumps({"error": "invalid_token", "error_description": reason}).encode()
        challenge = f'Bearer error="invalid_token", error_description="{reason}"'.encode()
        headers = [(b"content-type", b"application/json"), (b"www-authenticate", challenge)]
        await send({"type": "http.response.start", "status": 401, "headers": headers})
        await send({"type": "http.response.body", "body": body})
