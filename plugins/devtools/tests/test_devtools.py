"""teapot-devtools (WP2.9): its own table, the core refusing it, and a setup that can be made to fail."""

from typing import Any

import pytest

from teapot.testing import PluginHarness
from teapot_devtools import FAIL_SETUP, Noted, Peeked, plugin


async def test_notes_go_to_the_plugins_own_table(teapot_harness: Any) -> None:
    harness: PluginHarness = await teapot_harness(plugin)
    assert await harness.invoke("devtools.note", {"text": "one"}) == Noted(notes=1)
    assert await harness.invoke("devtools.note", {"text": "two"}) == Noted(notes=2)
    assert await harness.admin.fetchval("SELECT count(*) FROM plugin_devtools.notes") == 2


async def test_the_core_schema_refuses_the_plugin(teapot_harness: Any) -> None:
    harness: PluginHarness = await teapot_harness(plugin)
    out = await harness.invoke("devtools.peek_core", {})
    assert isinstance(out, Peeked) and "permission denied for schema core" in out.refusal


async def test_the_failure_switch_fails_setup(teapot_harness: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(FAIL_SETUP, "1")
    with pytest.raises(RuntimeError, match=FAIL_SETUP):
        await teapot_harness(plugin)
