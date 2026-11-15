"""Instance settings come from TEABOT_PLUGIN_<ID>_<FIELD>, and a missing one stops the plugin loading."""

from pathlib import Path

import pytest
from pydantic import BaseModel, SecretStr

from teabot.sdk import Context, EmptyConfig, Plugin
from teabot.settings import load_settings
from teabot.testing import HarnessFactory

plugin = Plugin("wom")
type Ctx = Context[EmptyConfig]


class Keys(BaseModel):
    api_key: SecretStr
    groups: list[int] = []
    timeout: float = 5.0


keys = plugin.instance_settings(Keys)


@plugin.action()
async def which(ctx: Ctx) -> str:
    """The configured groups."""
    return ",".join(str(g) for g in keys.get().groups)


def test_fields_are_read_from_their_variables() -> None:
    found = keys.load({"TEABOT_PLUGIN_WOM_API_KEY": "s3cret", "TEABOT_PLUGIN_WOM_GROUPS": "[1, 2]"})
    assert found.api_key.get_secret_value() == "s3cret"
    assert (found.groups, found.timeout) == ([1, 2], 5.0)


def test_a_missing_or_wrong_setting_is_named() -> None:
    with pytest.raises(ValueError, match="TEABOT_PLUGIN_WOM_API_KEY: Field required"):
        keys.load({})
    with pytest.raises(ValueError, match="TEABOT_PLUGIN_WOM_TIMEOUT"):
        keys.load({"TEABOT_PLUGIN_WOM_API_KEY": "k", "TEABOT_PLUGIN_WOM_TIMEOUT": "soon"})


async def test_the_plugin_reads_them_when_it_loads(
    teabot_harness: HarnessFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TEABOT_PLUGIN_WOM_API_KEY", "k")
    monkeypatch.setenv("TEABOT_PLUGIN_WOM_GROUPS", "[7]")
    harness = await teabot_harness(plugin)
    assert await harness.call(which) == "7"


async def test_without_them_the_plugin_does_not_load(
    teabot_harness: HarnessFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TEABOT_PLUGIN_WOM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TEABOT_PLUGIN_WOM_API_KEY"):
        await teabot_harness(plugin)


def test_the_env_file_supplies_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TEABOT_PLUGIN_WOM_API_KEY", raising=False)
    env = tmp_path / "teabot.env"
    env.write_text("TEABOT_PLUGIN_WOM_API_KEY=from-file\n")
    load_settings(env)
    assert keys.load().api_key.get_secret_value() == "from-file"
    monkeypatch.delenv("TEABOT_PLUGIN_WOM_API_KEY")
