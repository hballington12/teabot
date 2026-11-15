"""The watchdog names the plugin holding the loop, and leaves a healthy loop alone."""

import asyncio
import logging
import sys
import time

import pytest

from teabot.watchdog import Watchdog, blamed


def plugin_code() -> object:
    return sys._getframe()  # pyright: ignore[reportPrivateUsage]


def test_the_innermost_plugin_frame_is_blamed() -> None:
    frame = plugin_code()
    found = blamed(frame, {"mine": __name__})  # type: ignore[arg-type]
    assert found is not None and found[0] == "mine" and found[1] == __file__
    assert blamed(frame, {"other": "teabot_other"}) is None  # type: ignore[arg-type]


async def test_a_blocked_loop_is_logged_once_with_the_plugin(caplog: pytest.LogCaptureFixture) -> None:
    dog = Watchdog(soft=0.2, hard=30.0, startup=30.0, packages={"mine": __name__})
    dog.arm()
    beat = asyncio.create_task(dog.beat())
    try:
        await asyncio.sleep(0.6)
        with caplog.at_level(logging.WARNING, logger="teabot.watchdog"):
            time.sleep(1.5)  # noqa: ASYNC251 - a plugin blocking the loop, on purpose
            await asyncio.sleep(0.6)
    finally:
        beat.cancel()
        await asyncio.sleep(0)
    blocked = [r for r in caplog.records if r.getMessage() == "event loop blocked"]
    assert len(blocked) == 1
    assert getattr(blocked[0], "plugin", None) == "mine"


async def test_a_healthy_loop_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    dog = Watchdog(soft=0.3, hard=30.0, startup=30.0, packages={"mine": __name__})
    dog.arm()
    beat = asyncio.create_task(dog.beat())
    with caplog.at_level(logging.WARNING, logger="teabot.watchdog"):
        await asyncio.sleep(1.2)
    beat.cancel()
    await asyncio.sleep(0)
    assert not [r for r in caplog.records if r.getMessage() == "event loop blocked"]
