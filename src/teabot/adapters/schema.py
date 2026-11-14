"""The schema builder (D29): an action's input model as Discord command JSON and as an MCP tool schema.

The field rules live in `teabot.sdk.inputs`; this module only maps them onto each front door's format.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from teabot.core.registry import ActionSource
from teabot.sdk import ActionSpec, Risk, Surface
from teabot.sdk.inputs import InputError, InputField, input_fields

SchemaError = InputError

CHAT_INPUT = 1
SUB_COMMAND = 1
OPTION_TYPES = {"string": 3, "integer": 4, "boolean": 5, "member": 6, "channel": 7, "role": 8}


@dataclass(frozen=True)
class SlashFields:
    """The slash options, required ones first as Discord demands, and the fields a modal collects."""

    options: list[dict[str, Any]]
    modal: tuple[str, ...]


def _option(field: InputField) -> dict[str, Any]:
    option: dict[str, Any] = {
        "type": OPTION_TYPES[field.kind],
        "name": field.name,
        "description": field.description,
        "required": field.required,
    }
    if field.choices is not None:
        option["choices"] = [{"name": str(value), "value": value} for value in field.choices]
    if field.max_length is not None:
        option["max_length"] = field.max_length
    if field.min_value is not None:
        option["min_value"] = field.min_value
    if field.max_value is not None:
        option["max_value"] = field.max_value
    return option


def slash_fields(model: type[BaseModel]) -> SlashFields:
    fields = input_fields(model)
    options = [_option(f) for f in fields if f.kind != "long"]
    options.sort(key=lambda o: not o["required"])
    return SlashFields(options, tuple(f.name for f in fields if f.kind == "long"))


def _subcommand(spec: ActionSpec[Any, Any]) -> dict[str, Any]:
    return {
        "type": SUB_COMMAND,
        "name": spec.name.partition(".")[2],
        "description": spec.summary[:100],
        "options": slash_fields(spec.input).options,
    }


def command_group(plugin_id: str, specs: Iterable[ActionSpec[Any, Any]]) -> dict[str, Any]:
    """One slash command per plugin, with a subcommand for each action on the slash surface (D32)."""
    return {
        "type": CHAT_INPUT,
        "name": plugin_id,
        "description": f"{plugin_id} commands",
        "options": [_subcommand(s) for s in specs if Surface.SLASH in s.surfaces],
    }


CONFIRM_FIELD = {
    "type": "string",
    "description": "The confirm value of a plan this tool returned. Leave it out to get a plan.",
}


def mcp_input_schema(spec: ActionSpec[Any, Any]) -> dict[str, Any]:
    """The tool's JSON schema. A destructive action gains the optional `confirm` the core adds (D21)."""
    schema = spec.input.model_json_schema()
    if spec.risk is Risk.DESTRUCTIVE:
        schema["properties"] = {**schema.get("properties", {}), "confirm": CONFIRM_FIELD}
    return schema


def tool_name(spec: ActionSpec[Any, Any]) -> str:
    return spec.name.replace(".", "_")


def commands_for(sources: Mapping[str, ActionSource]) -> list[dict[str, Any]]:
    """The command groups of the plugins that have at least one slash action (D32)."""
    groups = [command_group(plugin_id, source.actions.values()) for plugin_id, source in sources.items()]
    return [g for g in groups if g["options"]]
