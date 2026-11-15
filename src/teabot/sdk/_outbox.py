"""A post as the outbox stores it: JSON in `core.posts`, and back to what discord.py sends. Internal to the SDK.

Buttons and select menus are stored by their custom ids, which carry their calls, so a stored post rebuilds them
exactly. Encoding checks them first, so a post that Discord would refuse fails in the plugin's own code.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import discord

from teabot.sdk._views import _components, allowed_mentions  # pyright: ignore[reportPrivateUsage]
from teabot.sdk.components import Button, Option, Select, parse_custom_id, parse_select_id


def encode(
    content: str | None,
    embed: discord.Embed | None,
    ping: Iterable[int],
    buttons: Sequence[Button],
    select: Select | None,
) -> dict[str, Any]:
    """The post as JSON. Raises `ValueError` for buttons or a menu Discord would refuse."""
    _components(buttons, select)
    if content is None and embed is None:
        raise ValueError("A post needs content or an embed.")
    return {
        "content": content,
        "embed": embed.to_dict() if embed is not None else None,
        "ping": [int(i) for i in ping],
        "buttons": [
            {"id": b.bound.custom_id(), "label": b.label, "emoji": b.emoji, "style": b.style} for b in buttons
        ],
        "select": _select(select) if select is not None else None,
    }


def _select(select: Select) -> dict[str, Any]:
    return {
        "id": select.bound.custom_id(select.into),
        "kind": select.kind,
        "options": [
            {
                "label": o.label,
                "value": o.value,
                "emoji": o.emoji,
                "description": o.description,
                "default": o.default,
            }
            for o in select.options
        ],
        "min": select.min,
        "max": select.max,
        "placeholder": select.placeholder,
        "defaults": list(select.defaults),
    }


def _button(data: Mapping[str, Any]) -> Button:
    bound = parse_custom_id(str(data["id"]))
    assert bound is not None
    return Button(bound, str(data["label"]), data.get("emoji"), data.get("style", "secondary"))


def _menu(data: Mapping[str, Any]) -> Select:
    parsed = parse_select_id(str(data["id"]))
    assert parsed is not None
    bound, into = parsed
    options = tuple(Option(**o) for o in data.get("options", ()))
    defaults = tuple(int(i) for i in data.get("defaults", ()))
    return Select(
        bound, into, data["kind"], options, data["min"], data["max"], data.get("placeholder"), defaults
    )


def decode(message: Mapping[str, Any]) -> dict[str, Any]:
    """The keyword arguments for discord.py's `send` and `edit`. `view` is None for a post without components,
    which on an edit takes away any it had."""
    embed = message.get("embed")
    select = message.get("select")
    return {
        "content": message.get("content"),
        "embed": discord.Embed.from_dict(embed) if embed else None,
        "view": _components(
            [_button(b) for b in message.get("buttons", ())], _menu(select) if select else None
        ),
        "allowed_mentions": allowed_mentions(message.get("ping", ())),
    }
