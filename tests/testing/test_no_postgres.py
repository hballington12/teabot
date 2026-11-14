"""Without Postgres, the test fixtures stop the run and say how to start it, rather than failing every test."""

import os
import subprocess
import sys
from pathlib import Path


def test_the_fixtures_say_how_to_start_postgres(tmp_path: Path) -> None:
    (tmp_path / "test_needs_db.py").write_text("def test_db(teabot_pg):\n    pass\n")
    env = os.environ | {"TEABOT_TEST_PG_HOST": "127.0.0.1", "TEABOT_TEST_PG_PORT": "1"}
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-p",
            "teabot.testing.fixtures",
            "-p",
            "no:cacheprovider",
            ".",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert done.returncode != 0
    assert "could not reach Postgres at 127.0.0.1:1" in done.stdout
    assert "docker compose up -d --wait postgres" in done.stdout
