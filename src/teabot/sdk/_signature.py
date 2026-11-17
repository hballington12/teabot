"""An action's input and output models, read from its function's signature and docstring. Internal to the SDK.

- Each parameter is an input field, except the ones teabot fills in, which are told apart by their annotation.
- The docstring's `Args:` section describes every input, for Discord, MCP and the service API alike.
- `TextChannel`, `VoiceChannel`, `Role` and `Member` parameters are stored as Discord IDs, and resolved on every call.
- A `str` or a list of models as the return type is wrapped in a model, so every front door gets one.
"""

import inspect
import re
import types
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, Any, TypeAliasType, Union, cast, get_args, get_origin, get_type_hints

from pydantic import BaseModel, Field, create_model

from teabot.sdk._render import fields_shown
from teabot.sdk.actions import ActionError
from teabot.sdk.fields import ChannelRef, MemberRef, RoleRef, VoiceChannelRef
from teabot.sdk.guild import Guild, Member, Role, TextChannel, VoiceChannel

DESCRIPTION_MAX = 100
ARG_LINE = re.compile(r"^\s+(\w+)\s*:\s*(.+)$")
REFS: dict[Any, Any] = {
    TextChannel: ChannelRef,
    VoiceChannel: VoiceChannelRef,
    Role: RoleRef,
    Member: MemberRef,
}
NOT_FOUND = {
    TextChannel: "That channel is not a text channel in this server.",
    VoiceChannel: "That channel is not a voice channel in this server.",
    Role: "That role is not in this server.",
    Member: "That member is not in this server.",
}


class SignatureError(TypeError):
    """A function that cannot be an action or a job, with where it is and how to fix it."""


def where(func: Callable[..., Any]) -> str:
    code = getattr(func, "__code__", None)
    return f"{code.co_filename}:{code.co_firstlineno}" if code is not None else func.__qualname__


def unalias(annotation: Any) -> Any:
    """A `type X = ...` alias is what it names."""
    while isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__
    return annotation


def origin_of(annotation: Any) -> Any:
    annotation = unalias(annotation)
    return get_origin(annotation) or annotation


def args_section(doc: str | None) -> tuple[str, dict[str, str]]:
    """The docstring's summary, its first line, and its `Args:` entries by parameter name."""
    text = inspect.cleandoc(doc or "")
    summary = text.split("\n", 1)[0].strip()
    if "Args:" not in text:
        return summary, {}
    entries: dict[str, str] = {}
    last = ""
    for line in text.split("Args:", 1)[1].splitlines():
        if (m := ARG_LINE.match(line)) is not None:
            last = m.group(1)
            entries[last] = m.group(2).strip()
        elif line.strip() and last and line.startswith(" " * 8):
            entries[last] += " " + line.strip()
        elif line.strip() and not line.startswith(" "):
            break
    return summary, entries


def _optional_inner(annotation: Any) -> tuple[Any, bool]:
    """`X | None` is `X`, optional."""
    if get_origin(annotation) in (Union, types.UnionType):
        rest = [a for a in get_args(annotation) if a is not type(None)]
        if len(rest) == 1 and len(get_args(annotation)) == 2:
            return rest[0], True
    return annotation, False


@dataclass(frozen=True)
class Resolved:
    """A parameter that arrives as a Discord object, stored as its ID."""

    name: str
    kind: Any
    optional: bool
    many: bool = False


@dataclass(frozen=True)
class Inputs:
    """What a function takes from its caller, and what teabot fills in."""

    summary: str
    model: type[BaseModel]
    injected: dict[str, Any]
    resolved: tuple[Resolved, ...]
    # Parameters typed as a model, such as `filter: MemberFilter`, whose fields are inputs of their own: each
    # parameter's name, its model, and its fields.
    flattened: tuple[tuple[str, type[BaseModel], tuple[str, ...]], ...] = ()


def _field_type(name: str, annotation: Any, resolved: list[Resolved]) -> Any:
    inner, optional = _optional_inner(unalias(annotation))
    base, *extras = get_args(inner) if get_origin(inner) is Annotated else (inner,)
    if base in REFS:
        resolved.append(Resolved(name, base, optional))
        ref = REFS[base]
        return ref | None if optional else ref
    if get_origin(unalias(base)) is list and (element := get_args(unalias(base))[0]) in REFS:
        # A list of Discord objects is stored as a list of their IDs, keeping the list's own limits.
        resolved.append(Resolved(name, element, optional, many=True))
        stored: Any = list[REFS[element]]
        if extras:
            stored = Annotated[stored, *extras]
        return stored | None if optional else stored
    return annotation


def read_inputs(
    func: Callable[..., Any], name: str, *, injected: Mapping[Any, str], needs_docs: bool = True
) -> Inputs:
    """The input model of `func`. `injected` maps the annotations teabot fills in to what it fills them with."""
    hints = get_type_hints(func, include_extras=True)
    summary, described = args_section(func.__doc__)
    if needs_docs and not summary:
        raise SignatureError(
            f"{where(func)}: {name} needs a docstring; its first line is the command's summary"
        )
    fields: dict[str, Any] = {}
    filled: dict[str, Any] = {}
    resolved: list[Resolved] = []
    flattened: list[tuple[str, type[BaseModel], tuple[str, ...]]] = []
    params = list(inspect.signature(func).parameters.values())
    for param in params:
        annotation = hints.get(param.name, Any)
        what = injected.get(origin_of(annotation))
        if what is not None:
            filled[param.name] = what
            continue
        if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
            flattened.append(_flatten(func, name, param.name, annotation, (fields, {p.name for p in params})))
            continue
        description = described.get(param.name)
        if needs_docs and description is None:
            raise SignatureError(
                f"{where(func)}: {name} has no description for {param.name}. "
                f"Add a line under Args: in its docstring, such as `{param.name}: What it is.`"
            )
        if description is not None and len(description) > DESCRIPTION_MAX:
            raise SignatureError(
                f"{where(func)}: the description of {param.name} in {name} has {len(description)} characters, "
                f"and Discord allows {DESCRIPTION_MAX}. Shorten it."
            )
        default = ... if param.default is inspect.Parameter.empty else param.default
        field_type = _field_type(param.name, annotation, resolved)
        fields[param.name] = (field_type, Field(default, description=description))
    unknown = sorted(set(described) - set(fields))
    if unknown:
        raise SignatureError(
            f"{where(func)}: the Args: of {name} names {', '.join(unknown)}, which it does not take"
        )
    model = create_model(_model_name(name), **fields)
    return Inputs(summary, model, filled, tuple(resolved), tuple(flattened))


def _flatten(
    func: Callable[..., Any],
    name: str,
    param: str,
    model: type[BaseModel],
    taken: tuple[dict[str, Any], set[str]],
) -> tuple[str, type[BaseModel], tuple[str, ...]]:
    """Add a model parameter's fields to `fields`, each an input of its own, described by the model."""
    fields, params = taken
    for field_name, info in model.model_fields.items():
        if field_name in fields or field_name in params or field_name == "confirm":
            raise SignatureError(
                f"{where(func)}: {name}'s {param} has a field {field_name}, which another input or `confirm` "
                "already uses. Rename one."
            )
        fields[field_name] = (info.annotation, info)
    return param, model, tuple(model.model_fields)


def _model_name(name: str) -> str:
    return "".join(part.capitalize() for part in re.split(r"[._]", name)) + "Input"


async def resolve(guild: Guild, inputs: Inputs, data: BaseModel) -> dict[str, Any]:
    """The function's input arguments, with Discord IDs turned back into the objects they name."""
    values = {name: getattr(data, name) for name in type(data).model_fields}
    for param, model, names in inputs.flattened:
        values[param] = model.model_validate({n: values.pop(n) for n in names})
    for r in inputs.resolved:
        value = values[r.name]
        if value is None:
            continue
        if r.many:
            values[r.name] = [await _find(guild, r.kind, item) for item in value]
        else:
            values[r.name] = await _find(guild, r.kind, value)
    return values


async def _find(guild: Guild, kind: Any, value: int) -> Any:
    found: Any
    if kind is TextChannel:
        found = guild.get_text_channel(value)
    elif kind is VoiceChannel:
        found = guild.get_voice_channel(value)
    elif kind is Role:
        found = guild.get_role(value)
    else:
        found = await guild.get_member(value)
    if found is None:
        raise ActionError(NOT_FOUND[kind])
    return found


class Text(BaseModel):
    """A reply that is one piece of text."""

    text: str


@dataclass(frozen=True)
class Output:
    """The output model an action declares, and how its function's return value becomes one."""

    model: type[BaseModel]
    wrap: Callable[[Any], BaseModel]
    render: Callable[[Any], str] | None
    unwrap: Callable[[BaseModel], Any] = lambda out: out


def read_output(func: Callable[..., Any], name: str) -> Output:
    returned = get_type_hints(func).get("return")
    if returned is str:
        return Output(Text, lambda value: Text(text=value), _text, _text)
    if origin_of(returned) is list:
        (item,) = get_args(unalias(returned))
        if isinstance(item, type) and issubclass(item, BaseModel):
            items_type: Any = cast(Any, list)[item]
            model = create_model(_model_name(name).removesuffix("Input") + "Items", items=(items_type, ...))
            return Output(model, lambda value: model(items=value), _render_items, _items)
    if isinstance(returned, type) and issubclass(returned, BaseModel):
        render = getattr(returned, "render", None)
        return Output(returned, lambda value: value, (lambda out: out.render()) if callable(render) else None)
    raise SignatureError(
        f"{where(func)}: {name} must return a pydantic model, a list of models, or str, not {returned!r}"
    )


def _text(out: Any) -> Any:
    return out.text


def _items(out: Any) -> Any:
    return out.items


def _render_items(out: Any) -> str:
    items: list[BaseModel] = out.items
    if not items:
        return "Nothing to show."
    lines = (" · ".join(text for _, text in fields_shown(item)) for item in items)
    return "\n".join(f"- {line}" for line in lines)
