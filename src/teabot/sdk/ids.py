"""Plugin ids (D46). The pattern fits Discord command names and the Postgres schema and role names of D9."""

import re

PLUGIN_ID_RE = re.compile(r"[a-z][a-z0-9_]{1,31}")
# The admin plugin's command groups are reserved too, so no plugin can take /plugins, /audit or /tokens.
RESERVED_PLUGIN_IDS = frozenset({"core", "admin", "teabot", "plugin", "plugins", "audit", "tokens"})


class InvalidPluginId(ValueError):
    """A plugin id that breaks D46's pattern, or a reserved one."""


def check_plugin_id(plugin_id: str) -> str:
    """Return the id if it matches the pattern, which also makes it safe in SQL identifiers."""
    if not PLUGIN_ID_RE.fullmatch(plugin_id):
        raise InvalidPluginId(f"plugin id {plugin_id!r} must match {PLUGIN_ID_RE.pattern}")
    return plugin_id


def check_plugin_id_free(plugin_id: str) -> str:
    """As `check_plugin_id`, and refuse the ids the core keeps for itself."""
    if check_plugin_id(plugin_id) in RESERVED_PLUGIN_IDS:
        raise InvalidPluginId(f"plugin id {plugin_id!r} is reserved")
    return plugin_id
