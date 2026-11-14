"""The template's `setup.sh`, run against a fake `docker`, `curl` and `git` that record what they are asked."""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

# setup.sh is a bash script; on Windows it runs in WSL, as the quick start says, so this runs where it does.
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="setup.sh runs in WSL on Windows")

TEMPLATE = Path(__file__).parents[2] / "template"
INVITE = "https://discord.com/oauth2/authorize?client_id=1&scope=bot+applications.commands&permissions=8"
FAKE_DOCKER = f"""#!/usr/bin/env bash
echo "docker $*" >> "$CALLS"
case "$*" in
  "volume inspect"*) exit "${{VOLUME_EXISTS:-1}}" ;;
  *"teabot init"*) echo "database ready"; echo "invite: {INVITE}" ;;
esac
exit 0
"""


def fake(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def instance(tmp_path: Path) -> Path:
    root = tmp_path / "instance"
    shutil.copytree(TEMPLATE, root, ignore=shutil.ignore_patterns(".env", "teabot.env", "uv.lock"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake(bin_dir, "docker", FAKE_DOCKER)
    fake(bin_dir, "curl", '#!/usr/bin/env bash\necho "curl $*" >> "$CALLS"\n')
    fake(bin_dir, "git", '#!/usr/bin/env bash\necho "git $*" >> "$CALLS"\nmkdir -p .git\n')
    return root


def setup(root: Path, typed: str = "", **env: str) -> subprocess.CompletedProcess[str]:
    path = f"{root.parent / 'bin'}:{os.environ['PATH']}"
    return subprocess.run(
        ["bash", "setup.sh"],
        cwd=root,
        input=typed,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": path, "CALLS": str(root.parent / "calls"), **env},
        check=False,
    )


def calls(root: Path) -> list[str]:
    return (root.parent / "calls").read_text().splitlines()


def test_a_first_run_writes_both_files_starts_the_bot_and_prints_the_invite(instance: Path) -> None:
    done = setup(instance, "tok.en-1\n")
    assert done.returncode == 0, done.stderr
    compose = (instance / ".env").read_text()
    assert compose.startswith("TEABOT_DB_OWNER_PASSWORD=") and len(compose.split("\n")[0]) > 40
    assert stat.S_IMODE((instance / ".env").stat().st_mode) == 0o600
    assert "TEABOT_DISCORD_TOKEN=tok.en-1\n" in (instance / "teabot.env").read_text()
    assert stat.S_IMODE((instance / "teabot.env").stat().st_mode) == 0o600
    assert "tok.en-1" not in done.stdout
    assert INVITE in done.stdout.split("teabot is running")[1]
    steps = [c for c in calls(instance) if c.startswith("docker compose") and "version" not in c]
    assert steps == [
        "docker compose build -q bot",
        "docker compose up -d --wait postgres",
        "docker compose run --rm bot teabot init",
        "docker compose up -d bot",
    ]
    assert "git init -q" in calls(instance)


def test_a_second_run_keeps_the_files_and_asks_for_nothing(instance: Path) -> None:
    assert setup(instance, "first\n").returncode == 0
    password = (instance / ".env").read_text()
    again = setup(instance)
    assert again.returncode == 0, again.stderr
    assert (instance / ".env").read_text() == password
    assert "TEABOT_DISCORD_TOKEN=first\n" in (instance / "teabot.env").read_text()
    assert "keeping it" in again.stdout


def test_a_database_without_its_env_file_is_refused_before_anything_changes(instance: Path) -> None:
    done = setup(instance, "tok\n", VOLUME_EXISTS="0")
    assert done.returncode == 1
    assert "would lock teabot out of" in done.stderr
    assert not (instance / ".env").exists() and not (instance / "teabot.env").exists()


def test_an_empty_token_stops_the_setup(instance: Path) -> None:
    done = setup(instance, "\n")
    assert done.returncode == 1 and "no token given" in done.stderr
