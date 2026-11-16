"""The input field types an action may use (D29), classified once for every front door.

Allowed: `str`, `LongText`, `int`, `bool`, `Literal` of all strings or all ints, and the `*Ref` types, each
optional or not, and a `list` of any of them but `LongText`, with `max_length` up to 10. A `ReceivedMessage` is
the target of a message's right-click menu, and no slash command takes one. Anything else is refused
with the field's name, so an action cannot be built with a field a front door could not offer.
"""

import types
from dataclasses import dataclass
from typing import Annotated, Any, Literal, TypeAliasType, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from teabot.sdk.fields import Long, Ref
from teabot.sdk.guild import ReceivedMessage

type InputKind = Literal[
    "string", "long", "integer", "boolean", "channel", "voice_channel", "role", "member", "message"
]
DESCRIPTION_MAX = 100
LIST_MAX = 10


class InputError(ValueError):
    """An input model uses a field type that D29 does not allow."""


@dataclass(frozen=True)
class InputField:
    name: str
    kind: InputKind
    required: bool
    description: str
    choices: tuple[str, ...] | tuple[int, ...] | None = None
    max_length: int | None = None
    min_value: int | None = None
    max_value: int | None = None
    count: int | None = None
    min_count: int = 0

    def option_names(self) -> list[str]:
        """The slash options it becomes: its own name, or for a list `roles_1` to `roles_<count>`."""
        if self.count is None:
            return [self.name]
        return [f"{self.name}_{n}" for n in range(1, self.count + 1)]


def _unwrap_optional(annotation: Any) -> Any:
    """`X | None` is `X`; whether the field is required is pydantic's answer, from its default."""
    if get_origin(annotation) in (Union, types.UnionType):
        args = get_args(annotation)
        rest = [a for a in args if a is not type(None)]
        if len(rest) == 1 and len(args) == 2:
            return rest[0]
    return annotation


def _split_annotated(annotation: Any, metadata: list[Any]) -> tuple[Any, list[Any]]:
    if get_origin(annotation) is Annotated:
        base, *extra = get_args(annotation)
        return base, _flatten([*metadata, *extra])
    return annotation, _flatten(metadata)


def _flatten(metadata: list[Any]) -> list[Any]:
    """A `Field(...)` inside an alias reaches here whole; its limits are in its own metadata."""
    out: list[Any] = []
    for m in metadata:
        out.extend(m.metadata if isinstance(m, FieldInfo) else [m])
    return out


def _literal_kind(name: str, values: tuple[Any, ...]) -> tuple[InputKind, tuple[Any, ...]]:
    if all(isinstance(v, str) for v in values):
        return "string", values
    if all(isinstance(v, int) and not isinstance(v, bool) for v in values):
        return "integer", values
    raise InputError(f"field {name}: a Literal must hold only strings or only ints")


def _kind(name: str, base: Any, metadata: list[Any]) -> tuple[InputKind, tuple[Any, ...] | None]:
    if get_origin(base) is Literal:
        return _literal_kind(name, get_args(base))
    refs = [m for m in metadata if isinstance(m, Ref)]
    if base is int and refs:
        return refs[0].kind, None
    simple: dict[Any, InputKind] = {int: "integer", bool: "boolean"}
    if base is str:
        return ("long" if any(isinstance(m, Long) for m in metadata) else "string"), None
    if base in simple:
        return simple[base], None
    if base is ReceivedMessage:
        return "message", None
    raise InputError(f"field {name}: {base!r} is not a supported input type (D29)")


def _describe(name: str, info: FieldInfo) -> str:
    text = info.description or name.replace("_", " ").capitalize()
    return text[:DESCRIPTION_MAX]


def _unalias(annotation: Any) -> Any:
    """A `type X = ...` alias is what it names."""
    while isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__
    return annotation


def _bound(metadata: list[Any], inclusive: str, exclusive: str, step: int) -> int | None:
    """An integer field's limit from `ge`/`le`, or from `gt`/`lt` moved one step inside."""
    for m in metadata:
        if isinstance(value := getattr(m, inclusive, None), int):
            return value
        if isinstance(value := getattr(m, exclusive, None), int):
            return value + step
    return None


def _limit(metadata: list[Any], key: str) -> int | None:
    return next((getattr(m, key) for m in metadata if getattr(m, key, None) is not None), None)


def _list_count(name: str, metadata: list[Any]) -> tuple[int, int]:
    count = _limit(metadata, "max_length")
    if count is None or not 1 <= count <= LIST_MAX:
        raise InputError(f"field {name}: a list needs Field(max_length=...) from 1 to {LIST_MAX}")
    return count, _limit(metadata, "min_length") or 0


def classify(name: str, info: FieldInfo) -> InputField:
    annotation = _unalias(_unwrap_optional(_unalias(info.annotation)))
    base, metadata = _split_annotated(annotation, list(info.metadata))
    count: int | None = None
    min_count = 0
    if get_origin(_unalias(base)) is list:
        count, min_count = _list_count(name, metadata)
        base, metadata = _split_annotated(_unalias(get_args(_unalias(base))[0]), [])
    kind, choices = _kind(name, base, metadata)
    if count is not None and kind == "long":
        raise InputError(f"field {name}: a list cannot hold LongText")
    max_length = _limit(metadata, "max_length")
    low = _bound(metadata, "ge", "gt", 1) if kind == "integer" else None
    high = _bound(metadata, "le", "lt", -1) if kind == "integer" else None
    return InputField(
        name,
        kind,
        info.is_required(),
        _describe(name, info),
        choices,
        max_length,
        low,
        high,
        count,
        min_count,
    )


def input_fields(model: type[BaseModel]) -> list[InputField]:
    """Every field of an input model, or `InputError` naming the first one that is not allowed."""
    return [classify(name, info) for name, info in model.model_fields.items()]
