"""What teabot-polls shows Discord, MCP clients and its queued jobs, kept in snapshot.json.

A change to a command, a tool or a job's payload fails this test with the difference. When the change is meant,
accept it with
`uv run --package teabot-polls pytest plugins/polls --teabot-accept`.
"""

from pathlib import Path

from teabot.testing import SnapshotCheck

from teabot_polls import plugin


def test_the_plugin_matches_its_snapshot(teabot_snapshot: SnapshotCheck) -> None:
    teabot_snapshot(plugin, Path(__file__).parent / "snapshot.json")
