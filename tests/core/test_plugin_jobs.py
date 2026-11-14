"""Plugin jobs and the command set of loaded plugins."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from teabot.adapters.schema import commands_for
from teabot.core.loader import Loaded
from teabot.core.plugin_jobs import register_plugin_jobs
from teabot.core.queue import NewJob, Queue
from teabot.core.registry import sources_from
from teabot.core.worker import Workers
from teabot.db.migrate import PluginMigrations, migrate
from teabot.db.naming import Naming
from teabot.db.pool import Pools
from teabot.db.types import Conn
from teabot.sdk import ActionSpec, JobContext, LongText, Manifest, Risk, Surface

GUILD = 1001


class Plugin:
    def __init__(self, plugin_id: str) -> None:
        self.manifest = Manifest(plugin_id, "1.0")

    def setup(self, registrar: Any) -> None:
        return None


@pytest.fixture
async def queue(admin: Conn, naming: Naming, pools: Pools, tmp_path: Path) -> Queue:
    directory = tmp_path / "alpha"
    directory.mkdir()
    (directory / "0001_t.sql").write_text("CREATE TABLE seen (guild_id bigint, note text);")
    await migrate(admin, naming, [PluginMigrations("alpha", directory)])
    await admin.execute(
        "INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled) VALUES ($1, 'alpha', true)", GUILD
    )
    return Queue(pools.core_db())


async def test_a_plugin_job_runs_with_its_server_payload_and_database(
    queue: Queue, pools: Pools, admin: Conn
) -> None:
    seen: dict[str, Any] = {}

    async def note(ctx: JobContext) -> None:
        seen.update(guild=ctx.guild_id, payload=dict(ctx.payload), client=ctx.client)
        await ctx.db.execute(
            "INSERT INTO seen (guild_id, note) VALUES ($1, $2)", ctx.guild_id, ctx.payload["note"]
        )
        await ctx.report({"done": 1})

    loaded = {"alpha": Loaded(Plugin("alpha"), jobs={"note": note})}
    client = object()
    register_plugin_jobs(queue, loaded, pools, client)  # type: ignore[arg-type]
    job_id = await queue.schedule(NewJob("alpha", "note", guild_id=GUILD, payload={"note": "hi"}))
    assert await Workers(queue, lambda: ["alpha"]).run_once()
    assert seen == {"guild": GUILD, "payload": {"note": "hi"}, "client": client}
    assert await admin.fetchval("SELECT note FROM plugin_alpha.seen") == "hi"
    assert await admin.fetchval("SELECT progress::text FROM core.jobs WHERE id = $1", job_id) == '{"done": 1}'


class Empty(BaseModel):
    pass


class Long(BaseModel):
    body: LongText


async def run(_ctx: Any, _data: Any) -> Empty:
    return Empty()


def test_the_command_set_has_a_group_per_plugin_with_slash_actions() -> None:
    loaded = {
        "alpha": Loaded(
            Plugin("alpha"),
            actions={
                "alpha.one": ActionSpec("alpha.one", "One", Empty, Empty, Risk.READ, run),
                "alpha.two": ActionSpec("alpha.two", "Two", Long, Empty, Risk.WRITE, run),
            },
        ),
        "beta": Loaded(
            Plugin("beta"),
            actions={
                "beta.hidden": ActionSpec(
                    "beta.hidden", "MCP only", Empty, Empty, Risk.READ, run, surfaces=Surface.MCP
                ),
            },
        ),
        "gamma": Loaded(Plugin("gamma")),
    }
    commands = commands_for(sources_from(loaded))
    assert [c["name"] for c in commands] == ["alpha"]
    assert [s["name"] for s in commands[0]["options"]] == ["one", "two"]


async def test_a_plugin_job_without_a_server_fails_with_a_reason(
    queue: Queue, pools: Pools, admin: Conn
) -> None:
    async def note(_ctx: JobContext) -> None:
        raise AssertionError("must not run")

    register_plugin_jobs(queue, {"alpha": Loaded(Plugin("alpha"), jobs={"note": note})}, pools, object())  # type: ignore[arg-type]
    job_id = await queue.schedule(NewJob("alpha", "note"))
    await admin.execute("UPDATE core.jobs SET max_attempts = 1 WHERE id = $1", job_id)
    assert await Workers(queue, lambda: ["alpha"]).run_once()
    assert "belongs to a server" in await admin.fetchval(
        "SELECT last_error FROM core.jobs WHERE id = $1", job_id
    )
