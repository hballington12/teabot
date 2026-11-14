"""Plugin snapshots: what the plugin shows the world, compared against a file, accepted on purpose."""

from pathlib import Path

import pytest
from tests.testing.test_helpers import plugin

from teabot.testing import SnapshotCheck, plugin_snapshot
from teabot.testing.snapshot import compare


def test_a_snapshot_holds_commands_tools_and_job_payloads() -> None:
    shot = plugin_snapshot(plugin)
    subcommands = {o["name"] for o in shot["commands"]["options"]}
    assert subcommands == {"greet", "times", "later", "clear"}
    assert set(shot["tools"]) == {"clocky_greet", "clocky_times", "clocky_later", "clocky_clear"}
    assert shot["jobs"]["note"]["properties"] == {"text": {"title": "Text", "type": "string"}}


def test_the_first_run_writes_the_snapshot_and_later_runs_compare(
    tmp_path: Path, teabot_snapshot: SnapshotCheck
) -> None:
    path = tmp_path / "snapshot.json"
    teabot_snapshot(plugin, path)
    assert path.exists()
    teabot_snapshot(plugin, path)


def test_a_change_fails_with_the_difference_and_how_to_accept_it(tmp_path: Path) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text('{"commands": {}}\n')
    with pytest.raises(pytest.fail.Exception) as caught:
        compare(plugin, path, accept=False)
    assert (
        "pytest plugins/" in str(caught.value)
        and "--teabot-accept" in str(caught.value)
        and '+  "jobs"' in str(caught.value)
    )
    compare(plugin, path, accept=True)
    compare(plugin, path, accept=False)
