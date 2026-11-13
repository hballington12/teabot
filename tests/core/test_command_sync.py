"""Per-server command sync (WP3.2, D32): global admin commands, a plugin's group only where it is enabled."""

from typing import Any

import pytest
from pydantic import BaseModel

from teapot.core.command_sync import SYNC_HANDLER, CommandSync, digest
from teapot.core.queue import JobContext, Queue
from teapot.core.registry import ActionSource
from teapot.db.migrate import migrate
from teapot.db.naming import Naming
from teapot.db.pool import Pools
from teapot.db.types import Conn
from teapot.sdk import ActionContext, ActionSpec, Risk
from teapot.testing import FakeClient

HERE = 1001
THERE = 1002


class NoInput(BaseModel):
    pass


async def nothing(ctx: ActionContext, data: NoInput) -> NoInput:
    return data


def source(group: str, *actions: str, builtin: bool = False) -> ActionSource:
    specs = {
        f"{group}.{a}": ActionSpec(f"{group}.{a}", f"{a} things", NoInput, NoInput, Risk.READ, nothing)
        for a in actions
    }
    return ActionSource(NoInput, specs, builtin=builtin)


SOURCES = {
    "beta": source("beta", "go"),
    "alpha": source("alpha", "go", "stop"),
    "plugins": source("plugins", "list", builtin=True),
}


class Broken(FakeClient):
    async def overwrite_commands(self, guild_id: int | None, commands: list[dict[str, Any]]) -> None:
        raise RuntimeError("Discord said no")


@pytest.fixture
async def queue(admin: Conn, naming: Naming, pools: Pools) -> Queue:
    await migrate(admin, naming, [])
    return Queue(pools.core_db())


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


@pytest.fixture
def sync(queue: Queue, pools: Pools, client: FakeClient) -> CommandSync:
    return CommandSync(pools.core_db(), queue, SOURCES, client)


async def enable(admin: Conn, guild_id: int, plugin_id: str, enabled: bool = True) -> None:
    await admin.execute(
        """INSERT INTO core.guild_plugins (guild_id, plugin_id, enabled) VALUES ($1, $2, $3)
        ON CONFLICT (guild_id, plugin_id) DO UPDATE SET enabled = EXCLUDED.enabled""",
        guild_id,
        plugin_id,
        enabled,
    )


async def run_syncs(queue: Queue, sync: CommandSync, pools: Pools) -> None:
    while (job := await queue.claim(["core"], None)) is not None:
        assert job.handler == SYNC_HANDLER
        await sync(JobContext(job, pools.core_db()))
        await queue.finish(job)


def names(commands: list[dict[str, Any]]) -> list[str]:
    return [c["name"] for c in commands]


async def test_a_server_gets_the_groups_of_the_plugins_enabled_there(
    admin: Conn, queue: Queue, sync: CommandSync, pools: Pools, client: FakeClient
) -> None:
    await enable(admin, HERE, "alpha")
    await sync.request(HERE)
    await run_syncs(queue, sync, pools)
    assert [(g, names(c)) for g, c in client.command_overwrites] == [(HERE, ["alpha"])]


async def test_syncing_an_unchanged_set_sends_nothing(
    admin: Conn, queue: Queue, sync: CommandSync, pools: Pools, client: FakeClient
) -> None:
    await enable(admin, HERE, "alpha")
    await sync.request(HERE)
    await sync.request(HERE)
    await run_syncs(queue, sync, pools)
    assert len(client.command_overwrites) == 1


async def test_disabling_the_last_plugin_clears_the_servers_commands(
    admin: Conn, queue: Queue, sync: CommandSync, pools: Pools, client: FakeClient
) -> None:
    await enable(admin, HERE, "alpha")
    await sync.request(HERE)
    await run_syncs(queue, sync, pools)
    await enable(admin, HERE, "alpha", enabled=False)
    await sync.request(HERE)
    await run_syncs(queue, sync, pools)
    assert client.command_overwrites[-1] == (HERE, [])


async def test_groups_are_in_a_stable_order(
    admin: Conn, queue: Queue, sync: CommandSync, pools: Pools, client: FakeClient
) -> None:
    await enable(admin, HERE, "beta")
    await enable(admin, HERE, "alpha")
    await sync.request(HERE)
    await run_syncs(queue, sync, pools)
    assert names(client.command_overwrites[0][1]) == ["alpha", "beta"]


async def test_a_plugin_enabled_but_not_loaded_has_no_commands(
    admin: Conn, queue: Queue, sync: CommandSync, pools: Pools, client: FakeClient
) -> None:
    await enable(admin, HERE, "gone")
    await enable(admin, HERE, "alpha")
    await sync.request(HERE)
    await run_syncs(queue, sync, pools)
    assert names(client.command_overwrites[0][1]) == ["alpha"]


async def test_the_admin_commands_are_global(
    queue: Queue, sync: CommandSync, pools: Pools, client: FakeClient
) -> None:
    await sync.request(None)
    await run_syncs(queue, sync, pools)
    assert [(g, names(c)) for g, c in client.command_overwrites] == [(None, ["plugins"])]


async def test_a_refused_overwrite_saves_no_hash_so_the_retry_sends_again(
    admin: Conn, queue: Queue, pools: Pools
) -> None:
    await enable(admin, HERE, "alpha")
    broken = CommandSync(pools.core_db(), queue, SOURCES, Broken())
    await broken.request(HERE)
    job = await queue.claim(["core"], None)
    assert job is not None
    with pytest.raises(RuntimeError, match="Discord said no"):
        await broken(JobContext(job, pools.core_db()))
    assert await admin.fetchval("SELECT count(*) FROM core.command_sync") == 0


async def test_startup_queues_only_what_changed(
    admin: Conn, queue: Queue, sync: CommandSync, pools: Pools, client: FakeClient
) -> None:
    await enable(admin, HERE, "alpha")
    assert await sync.startup() == 2
    await run_syncs(queue, sync, pools)
    await enable(admin, THERE, "beta")
    await enable(admin, HERE, "admin")
    assert await sync.startup() == 1
    await run_syncs(queue, sync, pools)
    assert [(g, names(c)) for g, c in client.command_overwrites][-1] == (THERE, ["beta"])
    assert await sync.startup() == 0


async def test_a_new_command_in_an_upgrade_resyncs_at_startup(
    admin: Conn, queue: Queue, sync: CommandSync, pools: Pools, client: FakeClient
) -> None:
    await enable(admin, HERE, "alpha")
    await sync.startup()
    await run_syncs(queue, sync, pools)
    upgraded = SOURCES | {"alpha": source("alpha", "go", "stop", "pause")}
    assert await CommandSync(pools.core_db(), queue, upgraded, client).startup() == 1


async def test_a_server_whose_plugins_are_all_gone_is_cleared_at_startup(
    admin: Conn, queue: Queue, sync: CommandSync, pools: Pools, client: FakeClient
) -> None:
    await enable(admin, HERE, "alpha")
    await sync.startup()
    await run_syncs(queue, sync, pools)
    await admin.execute("DELETE FROM core.guild_plugins")
    assert await sync.startup() == 1
    await run_syncs(queue, sync, pools)
    assert client.command_overwrites[-1] == (HERE, [])


def test_the_hash_is_of_the_content_not_the_key_order() -> None:
    assert digest([{"name": "a", "type": 1}]) == digest([{"type": 1, "name": "a"}])
    assert digest([{"name": "a"}]) != digest([{"name": "b"}])
