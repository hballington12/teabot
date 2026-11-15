"""Buttons on a post (D1, D32): each runs one of the plugin's actions, as the member who presses it.

`action.bind(...)` fixes the action's arguments, and a `Button` puts that call on a post:

```python
await channel.send("Pick your pings", buttons=[Button(toggle.bind(role=raids), label="Raids", emoji="🗡️")])
```

The call is written into the button's custom id, so a button needs nothing stored and keeps working after a
restart. Discord sends the id back only from the bot's own posts, and a press runs the action through the same
path as a slash command, checking the presser's permissions, so a button does nothing its action would not.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

PREFIX = "teabot:a:"
SELECT_PREFIX = "teabot:s:"
CUSTOM_ID_MAX = 100
BUTTONS_MAX = 25
BUTTONS_BESIDE_SELECT = 20
OPTIONS_MAX = 25

type ButtonStyle = Literal["primary", "secondary", "success", "danger"]
type SelectKind = Literal["options", "role", "channel", "member"]


@dataclass(frozen=True)
class BoundAction:
    """One of a plugin's actions with its arguments fixed, as `action.bind(...)` makes it.

    - `action` is the action's full name, such as `roles.toggle`.
    - `input` is its arguments as JSON values, as a slash command would send them.
    """

    action: str
    input: Mapping[str, Any]

    def custom_id(self, into: str | None = None) -> str:
        """The call, as a Discord custom id: a button's, or with `into` a select menu's, which fills that
        parameter with what is chosen. Raises `ValueError` when it does not fit Discord's 100 characters."""
        data = json.dumps(self.input, separators=(",", ":"), sort_keys=True)
        found = (
            f"{PREFIX}{self.action}:{data}" if into is None else f"{SELECT_PREFIX}{self.action}:{into}:{data}"
        )
        if len(found) > CUSTOM_ID_MAX:
            raise ValueError(
                f"{self.action}'s button holds {len(found)} characters, past Discord's {CUSTOM_ID_MAX}. "
                "Bind fewer or shorter arguments, such as an ID instead of a name."
            )
        return found


def _bound(action: str, raw: str) -> BoundAction | None:
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return BoundAction(action, cast(dict[str, Any], data)) if isinstance(data, dict) else None


def parse_custom_id(custom_id: str) -> BoundAction | None:
    """The call a button's custom id holds, or None when it is not one of teabot's buttons."""
    if not custom_id.startswith(PREFIX):
        return None
    action, _, raw = custom_id.removeprefix(PREFIX).partition(":")
    return _bound(action, raw)


def parse_select_id(custom_id: str) -> tuple[BoundAction, str] | None:
    """The call a select menu's custom id holds, and the parameter its choices fill, or None."""
    if not custom_id.startswith(SELECT_PREFIX):
        return None
    action, _, rest = custom_id.removeprefix(SELECT_PREFIX).partition(":")
    into, _, raw = rest.partition(":")
    bound = _bound(action, raw)
    return (bound, into) if bound is not None and into else None


@dataclass(frozen=True)
class Button:
    """A button on a post.

    - `bound` is the call it makes, from `action.bind(...)`.
    - `label` is its text, and `emoji` an emoji shown before it: a character such as `"🗡️"`, or a server emoji
      as Discord writes it, `"<:raids:123>"`.
    - `style` is its colour: `"primary"` (blurple), `"secondary"` (grey), `"success"` (green) or `"danger"`
      (red).
    """

    bound: BoundAction
    label: str
    emoji: str | None = None
    style: ButtonStyle = "secondary"


@dataclass(frozen=True)
class Option:
    """One choice in a select menu of options.

    - `label` is what the member sees, and `value` what the action receives, at most 100 characters each.
    - `emoji` is shown before it, and `description` under it.
    - `default` ticks it when the menu opens.
    """

    label: str
    value: str
    emoji: str | None = None
    description: str | None = None
    default: bool = False


@dataclass(frozen=True)
class Select:
    """A select menu on a post. What the member chooses fills one parameter of the bound action, `into`, which is
    a list: `list[str]` for a menu of `options`, or `list[Role]`, `list[TextChannel]` or `list[Member]` for
    Discord's own pickers, chosen by `kind`. That parameter needs a default, since the bound call leaves it out.

    - `bound` is the call, from `action.bind(...)`.
    - `kind` is `"options"` (the default), `"role"`, `"channel"` or `"member"`.
    - `options` are the choices of an `"options"` menu, up to 25.
    - `min` and `max` are how many may be chosen, from 0 to 25. `max` is 1 unless given, for a menu of one choice.
    - `placeholder` is shown before anything is chosen.
    - `defaults` are the IDs a role, channel or member picker shows chosen when it opens, such as the roles a
      member has. A menu of options ticks its own with `Option(default=True)` instead.
    """

    bound: BoundAction
    into: str
    kind: SelectKind = "options"
    options: tuple[Option, ...] = ()
    min: int = 0
    max: int = 1
    placeholder: str | None = None
    defaults: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.kind == "options" and not 1 <= len(self.options) <= OPTIONS_MAX:
            raise ValueError(
                f"A select menu of options holds 1 to {OPTIONS_MAX} options, not {len(self.options)}."
            )
        if self.defaults and self.kind == "options":
            raise ValueError("A menu of options ticks its defaults with Option(default=True), not defaults=.")
        if len(self.defaults) > self.max:
            raise ValueError(
                f"A select menu shows at most max={self.max} defaults, not {len(self.defaults)}."
            )
        if not 0 <= self.min <= self.max <= OPTIONS_MAX:
            raise ValueError(
                f"A select menu's min and max are from 0 to {OPTIONS_MAX}, with min at most max."
            )
