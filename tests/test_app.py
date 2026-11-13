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
