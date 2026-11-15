"""Settings for a whole instance (D10): what the operator sets once, such as an API key, as opposed to the
per-server config that admins change with `/plugins config`.

```python
class Keys(BaseModel):
    api_key: SecretStr

keys = plugin.instance_settings(Keys)

async def lookup(ctx: Ctx, name: str) -> str:
    token = keys.get().api_key.get_secret_value()
```

Each field is read from `TEABOT_PLUGIN_<ID>_<FIELD>`, such as `TEABOT_PLUGIN_WOM_API_KEY`, in `teabot.env` or the
environment. They are checked when the plugin loads, so a missing or wrong value stops the load with its name.
"""

import json
import os
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ValidationError

PREFIX = "TEABOT_PLUGIN_"


def variable(plugin_id: str, name: str) -> str:
    """The environment variable a setting is read from."""
    return f"{PREFIX}{plugin_id.upper()}_{name.upper()}"


def _value(raw: str) -> Any:
    """A list or an object written as JSON, such as `["a", "b"]`; anything else as the text it is."""
    if raw[:1] in "[{":
        try:
            return json.loads(raw)
        except ValueError:
            return raw
    return raw


class InstanceSettings[M: BaseModel]:
    """A plugin's settings for the whole instance, from `plugin.instance_settings(Model)`. `get()` returns them."""

    def __init__(self, plugin_id: str, model: type[M]) -> None:
        self.plugin_id = plugin_id
        self.model = model
        self._value: M | None = None

    def load(self, environ: Mapping[str, str] | None = None) -> M:
        """Read and check the settings. Raises `ValueError` naming each variable that is missing or wrong."""
        source = os.environ if environ is None else environ
        raw = {
            name: _value(source[variable(self.plugin_id, name)])
            for name in self.model.model_fields
            if variable(self.plugin_id, name) in source
        }
        try:
            self._value = self.model.model_validate(raw)
        except ValidationError as exc:
            problems = "; ".join(
                f"{variable(self.plugin_id, str(e['loc'][0]))}: {e['msg']}" for e in exc.errors() if e["loc"]
            )
            raise ValueError(f"{self.plugin_id}'s instance settings: {problems}") from None
        return self._value

    def get(self) -> M:
        """The settings, read when the plugin loaded."""
        return self._value if self._value is not None else self.load()
