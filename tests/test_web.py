"""`/healthz`: 200 when the gateway and database are fine, 503 otherwise, with the details either way."""

from typing import Any

import httpx
import pytest

from teabot.core.queue import NewJob, Queue
from teabot.db.migrate import migrate
from teabot.db.naming import Naming
from teabot.db.pool import Pools
from teabot.db.types import Conn
from teabot.health import Health
from teabot.web import build_app


@pytest.fixture
async def migrated(admin: Conn, naming: Naming, pools: Pools) -> Pools:
    await migrate(admin, naming, [])
    return pools


async def get(health: Health) -> tuple[int, dict[str, Any]]:
    """Call the app in this event loop, as the bot's loop does in production; asyncpg is bound to its loop."""
    transport = httpx.ASGITransport(app=build_app(health))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        response = await client.get("/healthz")
    return response.status_code, response.json()


async def test_healthy(migrated: Pools) -> None:
    await Queue(migrated.core_db()).schedule(NewJob("core", "x"))
    health = Health("1.2.3", migrated.core_db(), lambda: {0: 0.05, 1: 0.07}, lambda: {"alpha": "loaded"})
    status, body = await get(health)
    assert status == 200
    assert body == {
        "ok": True,
        "version": "1.2.3",
        "shards": {"0": 0.05, "1": 0.07},
        "database": True,
        "queue_backlog": 1,
        "plugins": {"alpha": "loaded"},
    }


@pytest.mark.parametrize("shards", [{0: 0.05, 1: None}, {}], ids=["a shard is down", "no shards yet"])
async def test_unhealthy_gateway(migrated: Pools, shards: dict[int, float | None]) -> None:
    health = Health("1", migrated.core_db(), lambda: shards, dict)
    status, body = await get(health)
    assert status == 503
    assert body["ok"] is False and body["database"] is True


async def test_unreachable_database(migrated: Pools) -> None:
    db = migrated.core_db()
    await migrated.core.close()
    health = Health("1", db, lambda: {0: 0.05}, dict)
    status, body = await get(health)
    assert status == 503
    assert body["database"] is False and body["queue_backlog"] is None
