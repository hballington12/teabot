"""A second package declaring the plugin id `devtools`, for the milestone 2 exit check (D46).

Installed only with `uv sync --group duplicate-check`. With it installed, neither devtools package loads, and
the bot reports both packages by name.
"""

from teapot.sdk import Manifest, Registrar


class DevtoolsTwin:
    manifest = Manifest("devtools", "0.0.1")

    def setup(self, registrar: Registrar) -> None:
        return None


plugin = DevtoolsTwin()
