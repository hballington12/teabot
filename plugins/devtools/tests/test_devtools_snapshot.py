"""What devtools shows Discord, MCP clients and its jobs, kept in snapshot.json."""

from pathlib import Path

from teabot.testing import SnapshotCheck
from teabot_devtools import plugin


def test_the_plugin_matches_its_snapshot(teabot_snapshot: SnapshotCheck) -> None:
    teabot_snapshot(plugin, Path(__file__).parent / "snapshot.json")
