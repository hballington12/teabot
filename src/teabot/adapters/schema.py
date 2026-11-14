"""The schema builder (D29): an action's input model as Discord command JSON and as an MCP tool schema.

The field rules live in `teabot.sdk.inputs`; this module only maps them onto each front door's format.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import reduce
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


def _options(field: InputField, suggested: bool) -> list[dict[str, Any]]:
    """A field's slash options: one, or for a list one per item, the first `min_count` of them required, and at
    least the first when the list is."""
    if field.count is None:
        return [_option(field, field.name, field.required, suggested)]
    needed = max(field.min_count, 1 if field.required else 0)
    return [
        _option(field, name, n <= needed, suggested) for n, name in enumerate(field.option_names(), start=1)
    ]


def field_of_option(model: type[BaseModel], option: str) -> str:
    """The input a slash option belongs to: itself, or for `roles_2` the list `roles`."""
    for field in input_fields(model):
        if option in field.option_names():
            return field.name
    return option


def fold_lists(model: type[BaseModel], raw: dict[str, Any]) -> dict[str, Any]:
    """A slash command's options as the action takes them: a list's numbered options gathered into one list, in
    order, skipping the ones left empty."""
    folded = dict(raw)
    for field in input_fields(model):
        if field.count is None:
            continue
        items = [folded.pop(name) for name in field.option_names() if name in folded]
        if items:
            folded[field.name] = items
    return folded


def _option(field: InputField, name: str, required: bool, suggested: bool = False) -> dict[str, Any]:
    option: dict[str, Any] = {
        "type": OPTION_TYPES[field.kind],
        "name": name,
        "description": field.description,
        "required": required,
    }
    if suggested:
        option["autocomplete"] = True
    if field.choices is not None:
        option["choices"] = [{"name": str(value), "value": value} for value in field.choices]
    if field.max_length is not None:
        option["max_length"] = field.max_length
    if field.min_value is not None:
        option["min_value"] = field.min_value
    if field.max_value is not None:
        option["max_value"] = field.max_value
    return option


def slash_fields(model: type[BaseModel], suggested: Iterable[str] = ()) -> SlashFields:
    fields = input_fields(model)
    names = set(suggested)
    options = [option for f in fields if f.kind != "long" for option in _options(f, f.name in names)]
    options.sort(key=lambda o: not o["required"])
    return SlashFields(options, tuple(f.name for f in fields if f.kind == "long"))


def _subcommand(spec: ActionSpec[Any, Any]) -> dict[str, Any]:
    return {
        "type": SUB_COMMAND,
        "name": spec.name.partition(".")[2],
        "description": spec.summary[:100],
        "options": slash_fields(spec.input, spec.suggest).options,
    }


def command_group(plugin_id: str, specs: Iterable[ActionSpec[Any, Any]]) -> dict[str, Any]:
    """One slash command per plugin, with a subcommand for each action on the slash surface (D32).

    Discord takes one permission setting per top-level command, so the command shows only to members holding
    the permissions all of its subcommands need. With none in common it shows to everyone, since Discord reads
    "0" as administrators only. The call path still checks each action's own permissions (D18).
    """
    slash = [s for s in specs if Surface.SLASH in s.surfaces]
    group: dict[str, Any] = {
        "type": CHAT_INPUT,
        "name": plugin_id,
        "description": f"{plugin_id} commands",
        "options": [_subcommand(s) for s in slash],
    }
    shared = shared_permissions(slash)
    if shared:
        group["default_member_permissions"] = str(shared)
    return group


def shared_permissions(specs: Iterable[ActionSpec[Any, Any]]) -> int:
    """The permission bits every one of these actions needs, or 0 when they share none."""
    values = [s.default_permissions.value for s in specs]
    return reduce(lambda a, b: a & b, values) if values else 0


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
