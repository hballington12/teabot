"""The bearer check on `/mcp` and `/api` (WP4.1, D16): refuse without a good token, else hand on the grant."""

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from teabot.auth.middleware import BearerTokens, grant_of
from teabot.auth.tokens import NewToken, Tokens
from teabot.db.migrate import migrate
from teabot.db.naming import Naming
from teabot.db.pool import Pools
from teabot.db.types import Conn


async def whoami(request: Request) -> JSONResponse:
    grant = grant_of(request)
    return JSONResponse({"user": grant.user_id, "guild": grant.guild_id})


async def open_route(_request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


@pytest.fixture
async def tokens(admin: Conn, naming: Naming, pools: Pools) -> Tokens:
    await migrate(admin, naming, [])
    return Tokens(pools.core_db())


@pytest.fixture
def client(tokens: Tokens) -> httpx.AsyncClient:
    app = Starlette(routes=[Route("/api/whoami", whoami), Route("/healthz", open_route)])
    guarded = BearerTokens(app, tokens, prefixes=("/api", "/mcp"))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=guarded), base_url="http://teabot")


async def test_a_good_token_reaches_the_route_as_its_member(
    client: httpx.AsyncClient, tokens: Tokens
) -> None:
    issued = await tokens.issue(1001, 2001, NewToken("claude"))
    response = await client.get("/api/whoami", headers={"Authorization": f"Bearer {issued.token}"})
    assert (response.status_code, response.json()) == (200, {"user": 2001, "guild": 1001})


@pytest.mark.parametrize("header", [None, "Bearer", "Basic abc", "Bearer teabot_nope_nope"])
async def test_without_a_good_token_the_answer_is_401_with_a_challenge(
    client: httpx.AsyncClient, header: str | None
) -> None:
    response = await client.get("/api/whoami", headers={"Authorization": header} if header else {})
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith('Bearer error="invalid_token"')
    assert response.json()["error"] == "invalid_token"


async def test_the_refusal_says_why_without_echoing_the_token(
    client: httpx.AsyncClient, tokens: Tokens
) -> None:
    issued = await tokens.issue(1001, 2001, NewToken("claude"))
    await tokens.revoke(issued.token_id, 1001)
    response = await client.get("/api/whoami", headers={"Authorization": f"Bearer {issued.token}"})
    assert response.json()["error_description"] == "this token was revoked"
    assert issued.token not in response.text


async def test_routes_outside_the_guarded_prefixes_need_no_token(client: httpx.AsyncClient) -> None:
    assert (await client.get("/healthz")).status_code == 200


async def test_a_prefix_guards_only_whole_path_segments(client: httpx.AsyncClient) -> None:
    assert (await client.get("/apiary")).status_code == 404


@pytest.mark.parametrize("header", ["Basic teabot_a_b", "Bearer   "])
async def test_anything_but_a_bearer_token_is_told_so(client: httpx.AsyncClient, header: str) -> None:
    response = await client.get("/api/whoami", headers={"Authorization": header})
    assert response.json()["error_description"] == "a bearer token is required"
