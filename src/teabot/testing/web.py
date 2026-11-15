"""The web as a plugin's tests see it: `harness.web` answers `ctx.http`'s requests with what the test set."""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from teabot.sdk import http


@dataclass(frozen=True)
class SentRequest:
    """A request the plugin sent: its `method`, `url`, `headers` and `body` as text."""

    method: str
    url: str
    headers: dict[str, str]
    body: str


@dataclass
class FakeWeb:
    """Answers each URL with the reply set by `reply`, and records every request in `requests`. A URL with no
    reply fails the test with what was asked."""

    replies: dict[str, httpx.Response] = field(default_factory=dict[str, httpx.Response])
    requests: list[SentRequest] = field(default_factory=list[SentRequest])

    def reply(self, url: str, *, json_body: Any = None, text: str = "", status: int = 200) -> None:
        """Answer `url`, with its query string if it has one, with `json_body` as JSON or `text`."""
        content = json.dumps(json_body) if json_body is not None else text
        self.replies[url] = httpx.Response(status, text=content)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requests.append(
            SentRequest(request.method, url, dict(request.headers), request.content.decode(errors="replace"))
        )
        found = self.replies.get(url) or self.replies.get(url.split("?", 1)[0])
        if found is None:
            raise AssertionError(f"the plugin asked for {request.method} {url}, which the test gave no reply")
        return found

    def install(self) -> None:
        """Send every plugin's `ctx.http` requests here."""
        http.use_transport(httpx.MockTransport(self._handle))
