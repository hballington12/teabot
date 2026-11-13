"""The HTTP app. `/healthz` now; `/mcp` and `/api` arrive in milestone 4 (D28, D36)."""

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from teapot.health import Health


def build_app(health: Health) -> Starlette:
    async def healthz(_request: Request) -> JSONResponse:
        report = await health.check()
        return JSONResponse(report.body, status_code=200 if report.ok else 503)

    return Starlette(routes=[Route("/healthz", healthz)])
