"""The input field types an action may use (D29), classified once for every front door.

Allowed: `str`, `LongText`, `int`, `bool`, `Literal` of all strings or all ints, and the `*Ref` types, each
optional or not. Anything else is refused with the field's name, so an action cannot be built with a field
a front door could not offer.
"""

import types
from dataclasses import dataclass
from typing import Annotated, Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from teapot.sdk.fields import Long, Ref

type InputKind = Literal["string", "long", "integer", "boolean", "channel", "role", "member"]
DESCRIPTION_MAX = 100


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
        return base, [*metadata, *extra]
    return annotation, metadata


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
    raise InputError(f"field {name}: {base!r} is not a supported input type (D29)")


def _describe(name: str, info: FieldInfo) -> str:
    text = info.description or name.replace("_", " ").capitalize()
    return text[:DESCRIPTION_MAX]


def classify(name: str, info: FieldInfo) -> InputField:
    base, metadata = _split_annotated(_unwrap_optional(info.annotation), list(info.metadata))
    kind, choices = _kind(name, base, metadata)
    max_length = next((m.max_length for m in metadata if getattr(m, "max_length", None) is not None), None)
    return InputField(name, kind, info.is_required(), _describe(name, info), choices, max_length)


def input_fields(model: type[BaseModel]) -> list[InputField]:
    """Every field of an input model, or `InputError` naming the first one that is not allowed."""
    return [classify(name, info) for name, info in model.model_fields.items()]
