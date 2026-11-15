"""How an output's values are shown in Discord when the action has no `render` of its own. Internal to the SDK.

Values are shown by their type: a `datetime` as a Discord timestamp, which each viewer sees in their own time
zone; a `ChannelRef`, `RoleRef` or `MemberRef` as a mention; `True` and `False` as yes and no; a list item by item.
"""

import types
from datetime import datetime
from typing import Annotated, Any, Union, cast, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from teabot.sdk.fields import Ref

MENTIONS = {"channel": "<#{}>", "role": "<@&{}>", "member": "<@{}>"}


def _ref_of(annotation: Any, metadata: list[Any]) -> Ref | None:
    """The `Ref` a field's type carries, through `Annotated`, `| None` and lists."""
    found = next((m for m in metadata if isinstance(m, Ref)), None)
    if found is not None:
        return found
    if get_origin(annotation) is Annotated:
        _, *extra = get_args(annotation)
        found = next((m for m in extra if isinstance(m, Ref)), None)
        if found is not None:
            return found
    if get_origin(annotation) in (Union, types.UnionType, list):
        for arg in get_args(annotation):
            inner = _ref_of(arg, [])
            if inner is not None:
                return inner
    return None


def shown(value: Any, info: FieldInfo | None = None) -> str:
    """One value as Discord shows it."""
    ref = _ref_of(info.annotation, list(info.metadata)) if info is not None else None
    if value is None:
        return "none"
    if isinstance(value, list | tuple):
        items: list[Any] = list(cast(Any, value))
        return ", ".join(_one(item, ref) for item in items) or "none"
    return _one(value, ref)


def _one(value: Any, ref: Ref | None) -> str:
    if ref is not None and isinstance(value, int):
        return MENTIONS[ref.kind].format(value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        return f"<t:{int(value.timestamp())}:f>"
    return str(value)


def fields_shown(model: BaseModel) -> list[tuple[str, str]]:
    """Each field of an output, by name, as Discord shows it."""
    return [(name, shown(getattr(model, name), info)) for name, info in type(model).model_fields.items()]
