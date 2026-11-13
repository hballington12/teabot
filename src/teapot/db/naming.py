"""Names of the database roles and schemas (D9, D46).

Roles live across the whole Postgres server, so every name hangs off one prefix. Instances use the
default `teapot`; tests use a random prefix so they never collide.
"""

import re
from dataclasses import dataclass

from teapot.sdk.ids import InvalidPluginId, check_plugin_id

__all__ = ["InvalidPluginId", "Naming", "check_plugin_id"]

_PREFIX_RE = re.compile(r"[a-z][a-z0-9_]{0,15}")


@dataclass(frozen=True)
class Naming:
    """Role and schema names for one instance."""

    prefix: str = "teapot"

    def __post_init__(self) -> None:
        if not _PREFIX_RE.fullmatch(self.prefix):
            raise ValueError(f"role prefix {self.prefix!r} must match {_PREFIX_RE.pattern}")

    @property
    def app_role(self) -> str:
        """The core pool's login role."""
        return f"{self.prefix}_app"

    @property
    def plugins_role(self) -> str:
        """The plugin pool's login role, with no rights of its own (S1)."""
        return f"{self.prefix}_plugins"

    def plugin_role(self, plugin_id: str) -> str:
        return f"{self.prefix}_plugin_{check_plugin_id(plugin_id)}"

    @staticmethod
    def plugin_schema(plugin_id: str) -> str:
        return f"plugin_{check_plugin_id(plugin_id)}"
