"""Snapshots of what a plugin shows the world: its slash commands, its MCP tools and its jobs' payloads.

A renamed parameter renames a slash option and an MCP field, a renamed job strands the jobs already queued, and a
changed job parameter breaks their stored payloads. A snapshot test makes each of those a visible choice: it fails
with the difference until the author accepts it with `pytest --teabot-accept`.
"""

import difflib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from teabot.adapters.schema import command_group, mcp_input_schema, tool_name
from teabot.sdk import ActionSpec, JobHandler, LoadablePlugin, Surface

ACCEPT = "--teabot-accept"


class _Collector:
    def __init__(self) -> None:
        self.actions: list[ActionSpec[Any, Any]] = []
        self.jobs: dict[str, JobHandler] = {}

    def action(self, spec: ActionSpec[Any, Any]) -> None:
        self.actions.append(spec)

    def job(self, name: str, handler: JobHandler) -> None:
        self.jobs[name] = handler


def plugin_snapshot(plugin: LoadablePlugin) -> dict[str, Any]:
    """What the plugin shows Discord, MCP clients and its queued jobs, as JSON."""
    collected = _Collector()
    plugin.setup(collected)
    specs = sorted(collected.actions, key=lambda s: s.name)
    tools = {tool_name(s): mcp_input_schema(s) for s in specs if Surface.MCP in s.surfaces}
    jobs = {name: _payload_schema(handler) for name, handler in sorted(collected.jobs.items())}
    return {"commands": command_group(plugin.manifest.id, specs), "tools": tools, "jobs": jobs}


def _payload_schema(handler: JobHandler) -> Any:
    """A decorated job's payload schema; a job registered by hand has none to snapshot."""
    job = getattr(handler, "__self__", None)
    inputs = getattr(job, "inputs", None)
    return inputs.model.model_json_schema() if inputs is not None else None


def compare(plugin: LoadablePlugin, path: Path, *, accept: bool) -> None:
    """Fail with the difference when the plugin no longer matches its snapshot at `path`. With `accept`, or
    when there is no snapshot yet, write it instead."""
    current = json.dumps(plugin_snapshot(plugin), indent=2, sort_keys=True) + "\n"
    if accept or not path.exists():
        path.write_text(current)
        return
    stored = path.read_text()
    if stored != current:
        diff = "".join(
            difflib.unified_diff(stored.splitlines(True), current.splitlines(True), str(path), "now")
        )
        pytest.fail(
            f"{plugin.manifest.id} no longer matches its snapshot. If the change is meant, run its tests again "
            f"with {ACCEPT}, such as\n"
            f"    uv run --package teabot-{plugin.manifest.id} pytest plugins/{plugin.manifest.id} {ACCEPT}\n\n{diff}",
            pytrace=False,
        )


type SnapshotCheck = Callable[[LoadablePlugin, Path], None]
"""The `teabot_snapshot` fixture: `teabot_snapshot(plugin, path)` compares the plugin with its snapshot file."""
