"""Outputs without a renderer of their own show their values by type."""

from datetime import UTC, datetime

from pydantic import BaseModel

from teabot.sdk import ChannelRef, MemberRef, RoleRef
from teabot.sdk._render import fields_shown

AT = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)


class Out(BaseModel):
    title: str
    at: datetime
    channel: ChannelRef
    role: RoleRef | None
    winners: list[MemberRef]
    open: bool
    ends: datetime | None = None


def test_times_show_as_discord_timestamps_and_ids_as_mentions() -> None:
    out = Out(title="Raid", at=AT, channel=1, role=2, winners=[3, 4], open=True)
    assert fields_shown(out) == [
        ("title", "Raid"),
        ("at", f"<t:{int(AT.timestamp())}:f>"),
        ("channel", "<#1>"),
        ("role", "<@&2>"),
        ("winners", "<@3>, <@4>"),
        ("open", "yes"),
        ("ends", "none"),
    ]
