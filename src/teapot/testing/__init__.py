"""Testing helpers for plugins and the core (D45).

- Fakes for a server, its members, roles and channels, and the client: `FakeGuild`, `FakeMember`, `FakeRole`,
  `FakeChannel`, `FakeVoiceChannel`, `FakeClient`. They are shaped like discord.py's objects.
- `PluginHarness`: a plugin loaded through the real loader and migrations, invoked through the real call path,
  as a member (`invoke`) or with a token (`invoke_with_token`).
- Postgres fixtures: add `-p teapot.testing.fixtures` to pytest's `addopts`, and install the `teapot[testing]`
  extra.
"""

from teapot.testing.fakes import (
    FakeCategory,
    FakeChannel,
    FakeClient,
    FakeGuild,
    FakeMember,
    FakeMessage,
    FakeRole,
    FakeVoiceChannel,
)
from teapot.testing.harness import PluginHarness, build_harness

__all__ = [
    "FakeCategory",
    "FakeChannel",
    "FakeClient",
    "FakeGuild",
    "FakeMember",
    "FakeMessage",
    "FakeRole",
    "FakeVoiceChannel",
    "PluginHarness",
    "build_harness",
]
