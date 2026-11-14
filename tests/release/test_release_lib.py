"""The release checks and steps, against a small copy of the repository's release files."""

import tarfile
from pathlib import Path

import pytest

from release_lib import (
    build_template,
    changelog_section,
    problems,
    template_ranges,
    version_of,
)

CHANGELOG = """# Changelog

## Unreleased

- Next.

## 1.2.0 - 2026-11-20

- Scheduling.

## 1.1.0 - 2026-10-01

- Hooks.
"""


def repo(tmp_path: Path, core: str = "1.2.0", ranges: str = ">=1.0,<2") -> Path:
    (tmp_path / "template").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(f'[project]\nname = "teabot"\nversion = "{core}"\n')
    (tmp_path / "template/pyproject.toml").write_text(
        f'[project]\nname = "i"\nversion = "0.1.0"\ndependencies = ["teabot{ranges}"]\n'
    )
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    return tmp_path


@pytest.mark.parametrize("tag", ["1.2.0", "v1.2", "v1.2.0rc1", "release-1"])
def test_a_tag_must_be_v_and_three_numbers(tag: str) -> None:
    with pytest.raises(ValueError, match=r"v<major>\.<minor>\.<patch>"):
        version_of(tag)


def test_a_matching_release_has_no_problems(tmp_path: Path) -> None:
    assert problems("v1.2.0", repo(tmp_path)) == []


def test_the_package_must_carry_the_tags_version(tmp_path: Path) -> None:
    assert problems("v1.2.0", repo(tmp_path, core="1.2.0.dev0")) == [
        "teabot is version 1.2.0.dev0, and the tag says 1.2.0"
    ]


def test_the_changelog_needs_a_section_for_the_version(tmp_path: Path) -> None:
    assert problems("v1.3.0", repo(tmp_path, core="1.3.0")) == ["CHANGELOG.md has no section headed ## 1.3.0"]


def test_the_template_must_accept_the_release_and_nothing_past_its_major(tmp_path: Path) -> None:
    assert problems("v1.2.0", repo(tmp_path, ranges=">=1.0")) == [
        "the template asks for teabot>=1.0, not teabot>=1.0,<2"
    ]


def test_a_section_runs_to_the_next_heading(tmp_path: Path) -> None:
    assert changelog_section(repo(tmp_path) / "CHANGELOG.md", "1.2.0") == "- Scheduling."
    assert changelog_section(repo(tmp_path / "x") / "CHANGELOG.md", "1.1.0") == "- Hooks."


def test_the_template_ranges_are_read_by_package(tmp_path: Path) -> None:
    assert template_ranges(repo(tmp_path) / "template/pyproject.toml") == {"teabot": ">=1.0,<2"}


def test_the_template_archive_holds_its_files_at_the_root_with_a_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = repo(tmp_path / "repo")
    (root / "template/.env").write_text("secret")
    (root / "template/plugins").mkdir()
    (root / "template/plugins/README.md").write_text("- yours")
    lock = '[[package]]\nname = "teabot"\nversion = "1.2.0"\n'

    def fake_lock(staging: Path, version: str, attempts: int, wait: float) -> None:
        (staging / "uv.lock").write_text(lock)

    monkeypatch.setattr("release_lib.lock_template", fake_lock)
    out = tmp_path / "teabot-template.tar.gz"
    build_template("1.2.0", out, root=root)
    with tarfile.open(out) as archive:
        assert sorted(archive.getnames()) == ["plugins/README.md", "pyproject.toml", "uv.lock"]
