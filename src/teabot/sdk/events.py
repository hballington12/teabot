"""Plugin events (events-and-tickets.md): what a plugin announces, for other plugins and outside programs.

- `Event(name, model, description)` declares one in `Plugin(emits=[...])`. Its full name is `<plugin>.<name>`.
- `tx.emit(payload)` emits one inside the plugin's transaction, picked by the payload's model.
- `@plugin.on_event("<plugin>.<name>", Model)` subscribes, and the handler receives a `Received[Model]`.

A payload holds only plain JSON fields: strings, numbers, booleans, dates, lists of these, and nested models of these.
A member's ID is a `MemberRef`, so deleting the member's data finds it, and member-written text is `UntrustedText`.
"""

import re
import types
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any, Literal, TypeAliasType, Union, cast, get_args, get_origin

from pydantic import BaseModel

from teabot.sdk._signature import SignatureError
from teabot.sdk.fields import Ref, Untrusted

EVENT_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
FULL_NAME = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")
PAYLOAD_MAX = 8 * 1024
"""The largest payload, in bytes of JSON: `UntrustedText` has no length of its own."""
EVENTS_PER_TRANSACTION = 100
"""The most events one transaction emits, so a bulk change emits in batches."""
SUBSCRIBER_ATTEMPTS = 13
"""Attempts a subscriber's job gets: the queue's doubling back-off then spans about two hours, so an outage that
long loses nothing. Discord events keep three, since they are about a moment."""

_PLAIN = (str, int, float, bool, date, datetime)


@dataclass(frozen=True)
class Event:
    """One event a plugin emits.

    - `name` is its name within the plugin, such as `accepted`, so its full name is `tickets.accepted`.
    - `model` is its payload's model, of its own: no two events of a plugin share one.
    - `description` says in a line what it means, for the plugin's docs and snapshot.
    """

    name: str
    model: type[BaseModel]
    description: str

    def __post_init__(self) -> None:
        if not EVENT_NAME.fullmatch(self.name):
            raise SignatureError(f"event {self.name!r}: a name is lower case letters, digits and underscores")
        if not self.description:
            raise SignatureError(f"event {self.name}: say in a line what it means")
        paths(self.model)


@dataclass(frozen=True)
class Paths:
    """Where in a payload its members' IDs and its member-written text sit, such as `claimant` or `items[].who`."""

    members: tuple[str, ...]
    untrusted: tuple[str, ...]


def _unwrap(annotation: Any) -> tuple[Any, list[Any]]:
    """The type under aliases, `Optional` and `Annotated`, and the `Annotated` metadata."""
    metadata: list[Any] = []
    while True:
        if isinstance(annotation, TypeAliasType):
            annotation = annotation.__value__
        elif get_origin(annotation) is Annotated:
            annotation, *extra = get_args(annotation)
            metadata.extend(extra)
        elif get_origin(annotation) in (Union, types.UnionType):
            rest = [a for a in get_args(annotation) if a is not type(None)]
            if len(rest) != 1:
                raise SignatureError(f"{annotation!r}: a payload field has one type, or that type or None")
            annotation = rest[0]
        else:
            return annotation, metadata


def _walk(annotation: Any, metadata: list[Any], path: str) -> Iterator[tuple[str, str]]:
    base, more = _unwrap(annotation)
    marks = [*metadata, *more]
    if any(isinstance(m, Ref) and m.kind == "member" for m in marks):
        yield "member", path
    if any(isinstance(m, Untrusted) for m in marks):
        yield "untrusted", path
    if get_origin(base) is list:
        (inner,) = get_args(base)
        yield from _walk(inner, [], f"{path}[]")
    elif isinstance(base, type) and issubclass(base, BaseModel):
        for name, info in base.model_fields.items():
            yield from _walk(info.annotation, list(info.metadata), f"{path}.{name}" if path else name)
    elif get_origin(base) is Literal:
        if not all(isinstance(v, (str, int)) for v in get_args(base)):
            raise SignatureError(f"{path}: a Literal in a payload holds strings or integers")
    elif base not in _PLAIN:
        raise SignatureError(
            f"{path}: {base!r} is not a payload type; use strings, numbers, booleans, dates, lists and models"
        )


def paths(model: type[BaseModel]) -> Paths:
    """Where a payload model holds members and member-written text, or `SignatureError` naming a field a
    payload may not hold."""
    found = list(_walk(model, [], ""))
    return Paths(
        tuple(p for kind, p in found if kind == "member"),
        tuple(p for kind, p in found if kind == "untrusted"),
    )


def values_at(data: Any, path: str) -> list[Any]:
    """The values at a path in a payload's JSON, such as every `who` in `items[].who`."""
    found = [data]
    for part in re.findall(r"[^.\[\]]+|\[\]", path):
        nxt: list[Any] = []
        for value in found:
            if part == "[]":
                if isinstance(value, list):
                    nxt.extend(cast(list[Any], value))
            elif isinstance(value, Mapping) and part in value:
                nxt.append(value[part])
        found = nxt
    return [v for v in found if v is not None]


# Each plugin's declared events, by payload model, so tx.emit finds the event from the payload alone.
_DECLARED: dict[tuple[str, type[BaseModel]], Event] = {}


def declare(plugin_id: str, events: list[Event]) -> None:
    """Record a plugin's events. A plugin declared again, as in tests, replaces its earlier declarations."""
    for key in [k for k in _DECLARED if k[0] == plugin_id]:
        del _DECLARED[key]
    names: set[str] = set()
    for event in events:
        if event.name in names:
            raise SignatureError(f"{plugin_id}: event {event.name} is declared twice")
        if (plugin_id, event.model) in _DECLARED:
            raise SignatureError(
                f"{plugin_id}: events {_DECLARED[(plugin_id, event.model)].name} and {event.name} share the model "
                f"{event.model.__name__}; give each event a model of its own"
            )
        names.add(event.name)
        _DECLARED[(plugin_id, event.model)] = event


def declared(plugin_id: str, model: type[BaseModel]) -> Event:
    """The plugin's event for a payload model, or `SignatureError` when it declared none."""
    found = _DECLARED.get((plugin_id, model))
    if found is None:
        raise SignatureError(
            f"{plugin_id} emitted a {model.__name__}, which it doesn't declare; add Event(...) to Plugin(emits=[...])"
        )
    return found


@dataclass(frozen=True)
class Received[T: BaseModel]:
    """An event as a subscriber receives it.

    - `id` grows with each event. For one thing, such as one ticket, a higher `id` is always later, so keep the
      last one applied for each thing and drop an older one: a retried job can arrive after a later event's.
    - `source` and `name` are the emitting plugin's ID and the event's name; `at` is when it happened.
    - `by` is the member who caused it, or None for the system, or 0 once their data was deleted.
    - `data` is the payload, validated into the subscriber's own model.

    Delivery is at least once, so a handler that changes something checks `id` first or makes the change
    idempotent.
    """

    id: int
    source: str
    name: str
    at: datetime
    by: int | None
    data: T
