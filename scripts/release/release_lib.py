"""What a release checks and makes (WP7.5): the scripts beside this file run these, and tests/release tests them.

A release is a tag `v<version>`. `teabot` and `teabot-announcements` carry that version, the changelog has a
section for it, and the template's dependencies accept it. The plugin is pinned to the exact core it was
released with (D45), and the template ships with a `uv.lock` made against the published packages.
"""

import re
import shutil
import subprocess
import tarfile
import time
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = "teabot"
PLUGIN = "teabot-announcements"
PLUGIN_PYPROJECT = "plugins/announcements/pyproject.toml"
SKIPPED = shutil.ignore_patterns(".venv", "__pycache__", "uv.lock", "teabot.env", ".env")


def version_of(tag: str) -> str:
    """The version a tag names: `v1.2.3` is `1.2.3`."""
    if not re.fullmatch(r"v\d+\.\d+\.\d+", tag):
        raise ValueError(f"a release tag is v<major>.<minor>.<patch>, not {tag!r}")
    return tag[1:]


def project_version(pyproject: Path) -> str:
    return tomllib.loads(pyproject.read_text())["project"]["version"]


def changelog_section(changelog: Path, version: str) -> str | None:
    """The changelog's section for `version`, under a heading such as `## 1.2.3 - 2026-11-20`, or None."""
    sections = re.split(r"^## ", changelog.read_text(), flags=re.M)[1:]
    for section in sections:
        heading, _, body = section.partition("\n")
        if heading.split(" ", 1)[0] == version:
            return body.strip()
    return None


def template_ranges(pyproject: Path) -> dict[str, str]:
    """The version range the template asks for, by package."""
    found: dict[str, str] = {}
    for dependency in tomllib.loads(pyproject.read_text())["project"]["dependencies"]:
        name, _, spec = dependency.partition(">=")
        found[name] = ">=" + spec if spec else ""
    return found


def problems(tag: str, root: Path = ROOT) -> list[str]:
    """Everything that stops `tag` being released, or nothing."""
    version = version_of(tag)
    found: list[str] = []
    for name, path in ((CORE, "pyproject.toml"), (PLUGIN, PLUGIN_PYPROJECT)):
        if (actual := project_version(root / path)) != version:
            found.append(f"{name} is version {actual}, and the tag says {version}")
    if changelog_section(root / "CHANGELOG.md", version) is None:
        found.append(f"CHANGELOG.md has no section headed ## {version}")
    major = int(version.split(".")[0])
    wanted = f">={major}.0,<{major + 1}"
    ranges = template_ranges(root / "template/pyproject.toml")
    found += [
        f"the template asks for {n}{ranges.get(n)}, not {n}{wanted}"
        for n in (CORE, PLUGIN)
        if ranges.get(n) != wanted
    ]
    return found


def pin_plugin(pyproject: Path, version: str) -> None:
    """Make the plugin depend on exactly the core it is released with."""
    text = pyproject.read_text()
    pinned = text.replace(f'dependencies = ["{CORE}"]', f'dependencies = ["{CORE}=={version}"]')
    if pinned == text:
        raise ValueError(f'{pyproject} has no dependencies = ["{CORE}"] line to pin')
    pyproject.write_text(pinned)


def locked_versions(lock: Path) -> dict[str, str]:
    return {
        p["name"]: p["version"] for p in tomllib.loads(lock.read_text()).get("package", []) if "version" in p
    }


def lock_template(staging: Path, version: str, attempts: int, wait: float) -> None:
    """Lock the template until it resolves to the release, which PyPI can take a minute to serve."""
    error = ""
    for attempt in range(1, attempts + 1):
        done = subprocess.run(
            ["uv", "lock", "--refresh", "-q"], cwd=staging, capture_output=True, text=True, check=False
        )
        error = done.stderr
        if done.returncode == 0:
            locked = locked_versions(staging / "uv.lock")
            if locked.get(CORE) == version and locked.get(PLUGIN) == version:
                return
        if attempt < attempts:
            time.sleep(wait)
    raise RuntimeError(f"the template did not lock to {version} after {attempts} attempts: {error}")


def build_template(version: str, out: Path, root: Path = ROOT, attempts: int = 10, wait: float = 30) -> None:
    """`teabot-template.tar.gz`: the template with its lock, its files at the archive's root."""
    staging = out.parent / "template-staging"
    shutil.rmtree(staging, ignore_errors=True)
    shutil.copytree(root / "template", staging, ignore=SKIPPED)
    lock_template(staging, version, attempts, wait)
    with tarfile.open(out, "w:gz") as archive:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                archive.add(path, arcname=str(path.relative_to(staging)))
    shutil.rmtree(staging)
