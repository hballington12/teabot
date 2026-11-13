"""Pieces of the app runner that do not need Discord (WP1.7). The whole runner is checked live against the
test server in the milestone 1 exit check."""

import math
from dataclasses import dataclass

import pytest

from teapot.app import TeapotClient, shard_latencies, token_or_exit


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
    assert shard_latencies(shards) == {0: 0.05, 1: None, 2: None, 3: None}


def test_no_shards_yet() -> None:
    assert shard_latencies({}) == {}


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
        self.uploads: list[tuple[int, int, list[dict[str, object]]]] = []

    async def bulk_upsert_guild_commands(
        self, app_id: int, guild_id: int, payload: list[dict[str, object]]
    ) -> None:
        self.uploads.append((app_id, guild_id, payload))


def client_with(
    commands: list[dict[str, object]] | None, dev_guild_id: int | None, app_id: int | None = 555
) -> tuple[TeapotClient, FakeHttp]:
    client = TeapotClient(lock=None, commands=commands, dev_guild_id=dev_guild_id)  # type: ignore[arg-type]
    http = FakeHttp()
    client.http = http  # type: ignore[assignment]
    client._connection.application_id = app_id  # pyright: ignore[reportPrivateUsage]
    return client, http


async def test_development_registers_the_commands_in_the_dev_server() -> None:
    client, http = client_with([{"name": "announcements"}], dev_guild_id=42)
    await client._register_dev_commands()  # pyright: ignore[reportPrivateUsage]
    assert http.uploads == [(555, 42, [{"name": "announcements"}])]


async def test_no_commands_registers_an_empty_set() -> None:
    client, http = client_with(None, dev_guild_id=42)
    await client._register_dev_commands()  # pyright: ignore[reportPrivateUsage]
    assert http.uploads == [(555, 42, [])]


@pytest.mark.parametrize(("dev_guild_id", "app_id"), [(None, 555), (42, None)])
async def test_without_a_dev_server_or_an_application_nothing_is_registered(
    dev_guild_id: int | None, app_id: int | None
) -> None:
    client, http = client_with([{"name": "announcements"}], dev_guild_id=dev_guild_id, app_id=app_id)
    await client._register_dev_commands()  # pyright: ignore[reportPrivateUsage]
    assert http.uploads == []


async def test_interactions_go_to_the_router_once_there_is_one() -> None:
    client, _ = client_with([], dev_guild_id=None)
    seen: list[object] = []

    class Router:
        async def handle(self, interaction: object) -> None:
            seen.append(interaction)

    await client.on_interaction("an interaction")  # type: ignore[arg-type]
    client.router = Router()  # type: ignore[assignment]
    await client.on_interaction("an interaction")  # type: ignore[arg-type]
    assert seen == ["an interaction"]
