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
CUSTOM_ID_MAX = 100
BUTTONS_MAX = 25

type ButtonStyle = Literal["primary", "secondary", "success", "danger"]


@dataclass(frozen=True)
class BoundAction:
    """One of a plugin's actions with its arguments fixed, as `action.bind(...)` makes it.

    - `action` is the action's full name, such as `roles.toggle`.
    - `input` is its arguments as JSON values, as a slash command would send them.
    """

    action: str
    input: Mapping[str, Any]

    def custom_id(self) -> str:
        """The call, as a Discord custom id. Raises `ValueError` when it does not fit Discord's 100 characters."""
        found = f"{PREFIX}{self.action}:{json.dumps(self.input, separators=(',', ':'), sort_keys=True)}"
        if len(found) > CUSTOM_ID_MAX:
            raise ValueError(
                f"{self.action}'s button holds {len(found)} characters, past Discord's {CUSTOM_ID_MAX}. "
                "Bind fewer or shorter arguments, such as an ID instead of a name."
            )
        return found


def parse_custom_id(custom_id: str) -> BoundAction | None:
    """The call a button's custom id holds, or None when it is not one of teabot's."""
    if not custom_id.startswith(PREFIX):
        return None
    action, _, raw = custom_id.removeprefix(PREFIX).partition(":")
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return BoundAction(action, cast(dict[str, Any], data)) if isinstance(data, dict) else None


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
