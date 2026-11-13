"""Testing helpers for plugins and the core (D45).

- Fakes for a server, its members and channels, and the client: `FakeGuild`, `FakeMember`, `FakeChannel`,
  `FakeClient`.
- `PluginHarness`: a plugin loaded through the real loader and migrations, invoked through the real call path.
- Postgres fixtures: add `pytest_plugins = ["teapot.testing.fixtures"]` to a `conftest.py`, and install the
  `teapot[testing]` extra.
"""

from teapot.testing.fakes import FakeChannel, FakeClient, FakeGuild, FakeMember, FakeMessage
from teapot.testing.harness import PluginHarness, build_harness

__all__ = [
    "FakeChannel",
    "FakeClient",
    "FakeGuild",
    "FakeMember",
    "FakeMessage",
    "PluginHarness",
    "build_harness",
]
