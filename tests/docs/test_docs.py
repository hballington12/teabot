"""The documentation site stays true to the code: the commands, the plugins, the settings and the scaffold."""

from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest

from teabot.cli.new_plugin import write_package
from teabot.plugins import announcements
from teabot.sdk import Plugin
from teabot.settings import Settings
from teabot.testing import HarnessFactory

ROOT = Path(__file__).parents[2]
DOCS = ROOT / "docs"
BUILT_IN = ("plugins", "audit", "tokens", "admin")


def command(action: str) -> str:
    """How the docs write an action: `giveaways.start` is `/giveaways start`."""
    group, _, name = action.partition(".")
    return f"`/{group} {name}`"


async def test_every_built_in_command_is_in_the_commands_table(teabot_harness: HarnessFactory) -> None:
    harness = await teabot_harness(announcements.plugin)
    built_in = [a for a in harness.registry.actions if a.split(".")[0] in BUILT_IN]
    page = (DOCS / "use/commands.md").read_text()
    assert len(built_in) >= 12
    assert [a for a in built_in if command(a) not in page] == []


def first_party() -> list[Plugin[Any]]:
    """Every plugin that ships inside teabot, from teabot's own entry points."""
    found = [
        ep.load() for ep in entry_points(group="teabot.plugins") if ep.value.startswith("teabot.plugins.")
    ]
    return sorted(found, key=lambda p: p.id)


@pytest.mark.parametrize("plugin", first_party(), ids=lambda p: p.id)
def test_every_first_party_plugin_has_a_page_naming_each_action(plugin: Plugin[Any]) -> None:
    page = (DOCS / f"use/plugins/{plugin.id}.md").read_text()
    assert [a for a in plugin.actions if command(a) not in page] == []


def test_the_env_example_names_every_setting() -> None:
    example = (ROOT / "template/teabot.env.example").read_text()
    missing = [n for n in Settings.model_fields if f"TEABOT_{n.upper()}=" not in example]
    assert missing == []


def test_the_first_plugin_page_shows_what_new_plugin_writes(tmp_path: Path) -> None:
    write_package(tmp_path / "polls", "polls")
    committed = ROOT / "tests/docs/scaffold/polls"
    rendered = sorted(
        p.relative_to(tmp_path / "polls") for p in (tmp_path / "polls").rglob("*") if p.is_file()
    )
    on_disk = sorted(
        p.relative_to(committed) for p in committed.rglob("*") if p.is_file() and "__pycache__" not in p.parts
    )
    assert rendered == on_disk
    # Text, not bytes, so the line endings a platform writes make no difference.
    differ = [p for p in rendered if (tmp_path / "polls" / p).read_text() != (committed / p).read_text()]
    assert differ == [], "re-render it: see tests/docs/README.md"
