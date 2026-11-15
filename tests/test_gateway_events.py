"""The client turns Discord's gateway events into plugin events, and drops what plugins must not hear."""

from types import SimpleNamespace
from typing import Any, cast

import pytest

from teabot.app import TeabotClient


class Recorder:
    """Stands in for the core's `Events`: every event is heard, and each one fired is kept."""

    def __init__(self) -> None:
        self.fired: list[tuple[int, str, dict[str, Any]]] = []

    def hears(self, event: str) -> bool:
        return True

    async def fire(self, guild_id: int, event: str, payload: dict[str, Any]) -> int:
        self.fired.append((guild_id, event, payload))
        return 1


@pytest.fixture
async def client() -> TeabotClient:
    made = TeabotClient(cast(Any, None))
    made.events = cast(Any, Recorder())
    return made


def fired(client: TeabotClient) -> list[tuple[int, str, dict[str, Any]]]:
    return cast(Recorder, client.events).fired


def ns(**values: Any) -> Any:
    return SimpleNamespace(**values)


async def test_a_persons_message_is_heard_and_a_bots_is_not(client: TeabotClient) -> None:
    guild, channel = ns(id=1), ns(id=2)
    await client.on_message(ns(id=3, guild=guild, channel=channel, author=ns(id=4, bot=False), content="hi"))
    await client.on_message(ns(id=5, guild=guild, channel=channel, author=ns(id=6, bot=True), content="beep"))
    await client.on_message(ns(id=7, guild=None, channel=channel, author=ns(id=4, bot=False), content="dm"))
    assert fired(client) == [
        (1, "message", {"message_id": 3, "channel_id": 2, "author_id": 4, "content": "hi"})
    ]


async def test_a_reaction_is_heard_unless_a_bot_made_it(client: TeabotClient) -> None:
    person = ns(guild_id=1, message_id=2, channel_id=3, user_id=4, emoji="⭐", member=ns(bot=False))
    bot = ns(guild_id=1, message_id=2, channel_id=3, user_id=5, emoji="⭐", member=ns(bot=True))
    await client.on_raw_reaction_add(person)
    await client.on_raw_reaction_add(bot)
    await client.on_raw_reaction_remove(person)
    assert [event for _, event, _ in fired(client)] == ["reaction_add", "reaction_remove"]
    assert fired(client)[0][2] == {"message_id": 2, "channel_id": 3, "user_id": 4, "emoji": "⭐"}


async def test_only_a_change_of_roles_is_heard(client: TeabotClient) -> None:
    guild = ns(id=1)
    before = ns(id=9, guild=guild, roles=[ns(id=10), ns(id=11)])
    after = ns(id=9, guild=guild, roles=[ns(id=11), ns(id=12)])
    await client.on_member_update(before, after)
    await client.on_member_update(after, after)
    assert fired(client) == [(1, "member_roles", {"user_id": 9, "added": [12], "removed": [10]})]


async def test_only_a_move_between_voice_channels_is_heard(client: TeabotClient) -> None:
    member = ns(id=9, guild=ns(id=1), bot=False)
    lounge = ns(id=20)
    await client.on_voice_state_update(member, ns(channel=None), ns(channel=lounge))
    await client.on_voice_state_update(member, ns(channel=lounge), ns(channel=lounge))
    assert fired(client) == [(1, "voice", {"user_id": 9, "left": None, "joined": 20})]
