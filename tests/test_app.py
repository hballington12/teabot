"""Pieces of the app runner that do not need Discord (WP1.7). The whole runner is checked live against the
test server in the milestone 1 exit check."""

import math
from dataclasses import dataclass

import pytest

from teapot.app import TeapotClient, public_hosts, shard_latencies, token_or_exit
from teapot.core.queue import ShardFilter
from teapot.settings import Settings


@dataclass
class FakeShard:
    latency: float
    closed: bool = False

    def is_closed(self) -> bool:
        return self.closed


def test_connected_shards_report_latency_and_others_none() -> None:
    shards = {
        0: FakeShard(0.05),
        1: FakeShard(0.07, closed=True),
        2: FakeShard(math.inf),
        3: FakeShard(math.nan),
    }
    assert shard_latencies(shards, ready=True) == {0: 0.05, 1: None, 2: None, 3: None}
    assert shard_latencies(shards, ready=False) == {0: None, 1: None, 2: None, 3: None}


def test_no_shards_yet() -> None:
    assert shard_latencies({}, ready=True) == {}


def test_a_missing_token_stops_the_run_with_a_message() -> None:
    with pytest.raises(SystemExit, match="TEAPOT_DISCORD_TOKEN"):
        token_or_exit("")
    assert token_or_exit("abc") == "abc"


async def test_the_client_caches_members_lazily_without_message_content() -> None:
    """Built, never started: discord.py only creates its shard queue on connect, so it is not closed here."""
    client = TeapotClient(lock=None)  # type: ignore[arg-type]
    assert client.intents.members is True
    assert client.intents.message_content is False
    assert client._connection._chunk_guilds is False  # pyright: ignore[reportPrivateUsage]


class FakeHttp:
    def __init__(self) -> None:
        self.uploads: list[tuple[int, int | None, list[dict[str, object]]]] = []

    async def bulk_upsert_guild_commands(
        self, app_id: int, guild_id: int, payload: list[dict[str, object]]
    ) -> None:
        self.uploads.append((app_id, guild_id, payload))

    async def bulk_upsert_global_commands(self, app_id: int, payload: list[dict[str, object]]) -> None:
        self.uploads.append((app_id, None, payload))


def client_with(app_id: int | None = 555) -> tuple[TeapotClient, FakeHttp]:
    client = TeapotClient(lock=None)  # type: ignore[arg-type]
    http = FakeHttp()
    client.http = http  # type: ignore[assignment]
    client._connection.application_id = app_id  # pyright: ignore[reportPrivateUsage]
    return client, http


@pytest.mark.parametrize("guild_id", [42, None])
async def test_an_overwrite_goes_to_one_server_or_to_the_global_commands(guild_id: int | None) -> None:
    client, http = client_with()
    await client.overwrite_commands(guild_id, [{"name": "announcements"}])
    assert http.uploads == [(555, guild_id, [{"name": "announcements"}])]


async def test_an_overwrite_before_login_is_refused() -> None:
    client, http = client_with(app_id=None)
    with pytest.raises(RuntimeError, match="not logged in"):
        await client.overwrite_commands(42, [])
    assert http.uploads == []


async def test_interactions_go_to_the_router_once_there_is_one() -> None:
    client, _ = client_with()
    seen: list[object] = []

    class Router:
        async def handle(self, interaction: object) -> None:
            seen.append(interaction)

    await client.on_interaction("an interaction")  # type: ignore[arg-type]
    client.router = Router()  # type: ignore[assignment]
    await client.on_interaction("an interaction")  # type: ignore[arg-type]
    assert seen == ["an interaction"]


class Lifecycle:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def joined(self, guild_id: int) -> None:
        self.calls.append(("joined", guild_id))

    async def removed(self, guild_id: int) -> None:
        self.calls.append(("removed", guild_id))

    async def reconcile(self, present: list[int], shards: ShardFilter) -> tuple[int, int]:
        self.calls.append(("reconcile", (present, shards)))
        return 0, 0


class Guild:
    def __init__(self, guild_id: int) -> None:
        self.id = guild_id


async def test_join_and_remove_events_reach_the_lifecycle_once_there_is_one() -> None:
    client, _ = client_with()
    await client.on_guild_join(Guild(7))  # type: ignore[arg-type]
    lifecycle = Lifecycle()
    client.lifecycle = lifecycle  # type: ignore[assignment]
    await client.on_guild_join(Guild(7))  # type: ignore[arg-type]
    await client.on_guild_remove(Guild(8))  # type: ignore[arg-type]
    assert lifecycle.calls == [("joined", 7), ("removed", 8)]


async def test_ready_compares_the_servers_on_this_processes_shards() -> None:
    client, _ = client_with()
    await client.on_ready()
    lifecycle = Lifecycle()
    client.lifecycle = lifecycle  # type: ignore[assignment]
    client.shard_count, client.shard_ids = 2, [1]
    await client.on_ready()
    assert lifecycle.calls == [("reconcile", ([], ShardFilter(shard_count=2, shard_ids=(1,))))]


@pytest.mark.parametrize(
    ("url", "hosts"),
    [
        (None, []),
        ("https://bot.example.org", ["bot.example.org"]),
        ("https://bot.example.org:8443/x", ["bot.example.org:8443"]),
    ],
)
def test_the_public_host_comes_from_the_public_url(url: str | None, hosts: list[str]) -> None:
    assert public_hosts(Settings(public_url=url)) == hosts
