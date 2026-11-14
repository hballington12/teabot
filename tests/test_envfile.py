"""The env-file helper used by `teabot init`."""

import stat
from pathlib import Path

from teabot.envfile import read_values, set_values


def test_set_values_replaces_appends_and_keeps_the_rest(tmp_path: Path) -> None:
    env = tmp_path / "teabot.env"
    env.write_text("# a comment\nTEABOT_A=1\n#TEABOT_B=commented\nTEABOT_C=3\n")
    set_values(env, {"TEABOT_A": "one", "TEABOT_B": "two"})
    assert env.read_text() == "# a comment\nTEABOT_A=one\n#TEABOT_B=commented\nTEABOT_C=3\nTEABOT_B=two\n"
    assert read_values(env) == {"TEABOT_A": "one", "TEABOT_C": "3", "TEABOT_B": "two"}


def test_set_values_makes_the_file_private(tmp_path: Path) -> None:
    env = tmp_path / "teabot.env"
    set_values(env, {"TEABOT_SECRET": "x"})
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_read_values_of_a_missing_file(tmp_path: Path) -> None:
    assert read_values(tmp_path / "absent.env") == {}
