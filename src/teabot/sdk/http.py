"""`ctx.http`: one shared HTTP client that reaches only the hosts a plugin declares (D12).

```python
plugin = Plugin("wom", hosts=["api.wiseoldman.net"])

async def rank(ctx: Ctx, name: str) -> str:
    found = await ctx.http.get(f"https://api.wiseoldman.net/v2/players/{name}")
    return found.json()["type"]
```

A host is declared by its exact name, and each one the plugin reaches is listed in its README's "External
connections" too, for review. Redirects are not followed, so a reply cannot send the request somewhere
undeclared. This is not a sandbox: a plugin could bring its own client, which `teabot check` flags.
"""

import json as jsonlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

# How many seconds a request may take, unless the call says otherwise.
DEFAULT_WAIT = 10.0
_shared: list[httpx.AsyncClient] = []


class HostNotDeclared(Exception):
    """The plugin asked `ctx.http` for a host it has not declared in `Plugin(..., hosts=[...])`."""


@dataclass(frozen=True)
class Response:
    """What a request got back.

    - `status` is the HTTP status, such as 200, and `ok` whether it is below 400.
    - `headers` are the reply's headers, by lower-case name.
    - `text` is the body as text; `json()` reads it as JSON.
    """

    status: int
    headers: Mapping[str, str]
    text: str

    @property
    def ok(self) -> bool:
        """Whether the request worked: a status below 400."""
        return self.status < 400

    def json(self) -> Any:
        """The body, read as JSON."""
        return jsonlib.loads(self.text)


def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Send every plugin's requests through `transport`, as `teabot.testing` does to answer them itself."""
    _shared.clear()
    if transport is not None:
        _shared.append(httpx.AsyncClient(transport=transport, follow_redirects=False))


def _client() -> httpx.AsyncClient:
    if not _shared:
        _shared.append(httpx.AsyncClient(follow_redirects=False))
    return _shared[0]


class Http:
    """The plugin's view of the shared HTTP client: `plugin_id` names it in requests, and only `hosts` are
    reached."""

    def __init__(self, plugin_id: str, hosts: frozenset[str]) -> None:
        self.plugin_id = plugin_id
        self.hosts = hosts

    def _check(self, url: str) -> None:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if parts.scheme not in ("http", "https") or host not in self.hosts:
            raise HostNotDeclared(
                f"{self.plugin_id} may not reach {host or url}; add it to Plugin(..., hosts=[...]) and to the "
                f"README's External connections"
            )

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        wait: float = DEFAULT_WAIT,
    ) -> Response:
        """Send a request to a declared host, waiting at most `wait` seconds. Raises `HostNotDeclared` for any
        other host, and `httpx`'s errors when the host cannot be reached in time."""
        self._check(url)
        sent = {"User-Agent": f"teabot plugin {self.plugin_id}", **(headers or {})}
        reply = await _client().request(method, url, params=params, json=json, headers=sent, timeout=wait)
        return Response(reply.status_code, {k.lower(): v for k, v in reply.headers.items()}, reply.text)

    async def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        wait: float = DEFAULT_WAIT,
    ) -> Response:
        """`GET` a declared host's `url`."""
        return await self.request("GET", url, params=params, headers=headers, wait=wait)

    async def post(
        self,
        url: str,
        *,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        wait: float = DEFAULT_WAIT,
    ) -> Response:
        """`POST` `json` to a declared host's `url`."""
        return await self.request("POST", url, json=json, headers=headers, wait=wait)
