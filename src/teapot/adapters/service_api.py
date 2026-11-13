"""The service API (D20): `POST /api/v1/actions/<name>` with `{"input": {...}}`, for event backends.

A request runs through the one call path as its token's member in its token's server, like an MCP call.
Outputs are plain JSON: a backend is not an LLM, so member text needs no marker here. A refusal answers with
a status a backend can act on and the registry's refusal code.
"""

import json
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from teapot.auth.middleware import grant_of
from teapot.core.registry import ActionFailed, Call, RefusalCode, Refused, Registry
from teapot.sdk import Actor

FAILED = "The action failed. Its audit row has the details."
BAD_BODY = 'The body must be a JSON object such as {"input": {...}}.'
# Not found: nothing by that name here. Forbidden: the token or member may not. Conflict: the server is not
# ready for it. Unprocessable: the input does not fit.
STATUS: dict[RefusalCode, int] = {
    "unknown_action": 404,
    "wrong_surface": 404,
    "above_token_risk": 403,
    "not_allowed_by_token": 403,
    "forbidden": 403,
    "not_in_guild": 409,
    "plugin_not_enabled": 409,
    "config_invalid": 409,
    "invalid_input": 422,
}


def problem(status: int, error: str, message: str) -> JSONResponse:
    return JSONResponse({"error": error, "message": message}, status_code=status)


def input_of(body: bytes) -> dict[str, Any] | None:
    """The `input` object of a request body, `{}` when it is left out, or None when the body is not one."""
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("input", {})  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    return raw if isinstance(raw, dict) else None  # pyright: ignore[reportUnknownVariableType]


class ServiceApi:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry

    def routes(self) -> list[Route]:
        return [Route("/api/v1/actions/{name}", self.act, methods=["POST"])]

    async def act(self, request: Request) -> JSONResponse:
        raw = input_of(await request.body())
        if raw is None:
            return problem(400, "bad_request", BAD_BODY)
        grant = grant_of(request)
        actor = Actor(grant.user_id, "service", grant.token_id)
        call = Call(request.path_params["name"], grant.guild_id, actor, raw, grant.limits)
        try:
            output = await self.registry.invoke(call)
        except Refused as refusal:
            return problem(STATUS[refusal.code], refusal.code, refusal.message)
        except ActionFailed as failure:
            if failure.public_message is not None:
                return problem(400, "action_error", failure.public_message)
            return problem(500, "action_failed", FAILED)
        return JSONResponse({"output": output.model_dump(mode="json")})
