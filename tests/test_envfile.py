"""The env-file helper used by `teapot init`."""

import stat
from pathlib import Path

from teapot.envfile import read_values, set_values


def test_set_values_replaces_appends_and_keeps_the_rest(tmp_path: Path) -> None:
    env = tmp_path / "teapot.env"
    env.write_text("# a comment\nTEAPOT_A=1\n#TEAPOT_B=commented\nTEAPOT_C=3\n")
    set_values(env, {"TEAPOT_A": "one", "TEAPOT_B": "two"})
    assert env.read_text() == "# a comment\nTEAPOT_A=one\n#TEAPOT_B=commented\nTEAPOT_C=3\nTEAPOT_B=two\n"
    assert read_values(env) == {"TEAPOT_A": "one", "TEAPOT_C": "3", "TEAPOT_B": "two"}


def test_set_values_makes_the_file_private(tmp_path: Path) -> None:
    env = tmp_path / "teapot.env"
    set_values(env, {"TEAPOT_SECRET": "x"})
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_read_values_of_a_missing_file(tmp_path: Path) -> None:
    assert read_values(tmp_path / "absent.env") == {}
