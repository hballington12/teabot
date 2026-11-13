"""The HTTP app (D28, D36): `/healthz` for anyone; `/mcp` and `/api` behind the bearer-token check.

The MCP session manager lives for the app's lifespan, so uvicorn runs with its lifespan on: startup and
shutdown happen in one task, which the SDK's task group needs.
"""

import contextlib
from collections.abc import AsyncGenerator

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Route

from teapot.adapters.mcp import McpAdapter
from teapot.adapters.service_api import ServiceApi
from teapot.auth.middleware import BearerTokens
from teapot.auth.tokens import Tokens
from teapot.core.registry import Registry
from teapot.health import Health

GUARDED = ("/mcp", "/api")


def build_app(
    health: Health,
    *,
    tokens: Tokens | None = None,
    mcp: McpAdapter | None = None,
    service: Registry | None = None,
) -> Starlette:
    async def healthz(_request: Request) -> JSONResponse:
        report = await health.check()
        return JSONResponse(report.body, status_code=200 if report.ok else 503)

    routes: list[BaseRoute] = [Route("/healthz", healthz)]
    if mcp is not None:
        routes.append(Route("/mcp", endpoint=mcp.asgi()))
    if service is not None:
        routes.extend(ServiceApi(service).routes())

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncGenerator[None]:
        async with mcp.run() if mcp is not None else contextlib.nullcontext():
            yield

    middleware = [] if tokens is None else [Middleware(BearerTokens, tokens=tokens, prefixes=GUARDED)]
    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)
