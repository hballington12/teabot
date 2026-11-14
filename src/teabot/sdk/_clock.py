"""The time actions and jobs see as `ctx.now`. Internal to the SDK: `teabot.testing` moves it forward in tests."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass
class Clock:
    """Real time, moved by however far a test has advanced it."""

    offset: timedelta = timedelta()

    def now(self) -> datetime:
        return datetime.now(UTC) + self.offset


CLOCK = Clock()


def now() -> datetime:
    """The current time in UTC, as actions and jobs see it."""
    return CLOCK.now()
