"""A second package declaring the plugin id `devtools`: two packages claiming one id both fail (D46).

Installed only with `uv sync --group duplicate-check`. With it installed, neither devtools package loads, and
the bot reports both packages by name.
"""

from teabot.sdk import Manifest, Registrar


class DevtoolsTwin:
    manifest = Manifest("devtools", "0.0.1")

    def setup(self, registrar: Registrar) -> None:
        return None


plugin = DevtoolsTwin()
