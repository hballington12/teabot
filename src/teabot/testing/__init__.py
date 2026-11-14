"""Testing helpers for plugins and the core (D45).

- Fakes for a server, its members, roles and channels, and the client: `FakeGuild`, `FakeMember`, `FakeRole`,
  `FakeChannel`, `FakeVoiceChannel`, `FakeClient`. They are shaped like discord.py's objects.
- `PluginHarness`: a plugin loaded through the real loader and migrations, invoked through the real call path,
  as a member (`invoke`) or with a token (`invoke_with_token`).
- What `invoke` raises and returns besides an action's output: `Refused` (with its `code`) before the action
  runs, `ActionFailed` (with its `public_message`) when it raised, and a destructive action's `Planned` and
  `Queued`. `JobFailed` is what `harness.run_jobs()` raises when a job fails, with the job's own exception as
  its cause.
- Postgres fixtures: add `-p teabot.testing.fixtures` to pytest's `addopts`, and install the `teabot[testing]`
  extra.
"""

from teabot.core.plans import Planned, Queued
from teabot.core.registry import ActionFailed, Refused
from teabot.testing.fakes import (
    FakeCategory,
    FakeChannel,
    FakeClient,
    FakeGuild,
    FakeMember,
    FakeMessage,
    FakeRole,
    FakeVoiceChannel,
)
from teabot.testing.harness import JobFailed, PluginHarness, build_harness

__all__ = [
    "ActionFailed",
    "FakeCategory",
    "FakeChannel",
    "FakeClient",
    "FakeGuild",
    "FakeMember",
    "FakeMessage",
    "FakeRole",
    "FakeVoiceChannel",
    "JobFailed",
    "Planned",
    "PluginHarness",
    "Queued",
    "Refused",
    "build_harness",
]
