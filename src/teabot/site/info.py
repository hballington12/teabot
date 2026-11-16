"""What the site says of each plugin the instance runs: its own manifest first, then the hub's listing."""

from collections.abc import Mapping
from dataclasses import dataclass

from teabot.catalogue import Listed
from teabot.sdk import Manifest


@dataclass(frozen=True)
class PluginInfo:
    """One installed plugin: its id and version, what it does, what it contacts beyond Discord, and whether the
    plugin hub lists it, for a link to its hub page."""

    id: str
    version: str
    description: str
    contacts: str
    on_hub: bool

    def summary(self) -> dict[str, str]:
        """What `/plugins.json` says of it."""
        return {"id": self.id, "version": self.version, "description": self.description}


def installed(manifests: Mapping[str, Manifest], hub: Mapping[str, Listed]) -> list[PluginInfo]:
    """The loaded plugins, by id. A description the plugin gives wins over the hub's, which is a snapshot of it."""
    found: list[PluginInfo] = []
    for plugin_id in sorted(manifests):
        manifest = manifests[plugin_id]
        listed = hub.get(plugin_id)
        chosen = listed.for_teabot() if listed is not None else None
        found.append(
            PluginInfo(
                plugin_id,
                manifest.version,
                manifest.description or (listed.description if listed is not None else ""),
                chosen.external_connections if chosen is not None else "",
                listed is not None,
            )
        )
    return found
