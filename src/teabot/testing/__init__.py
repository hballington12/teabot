"""Testing helpers for plugins and the core (D45).

- Fakes for a server, its members, roles and channels, and the client: `FakeGuild`, `FakeMember`, `FakeRole`,
  `FakeChannel`, `FakeVoiceChannel`, `FakeClient`. They are shaped like discord.py's objects. A `FakeChannel`
  keeps each `FakeMessage` it was sent, with its `FakeButton`s, which `harness.press` presses, and its
  `FakeSelect`, which `harness.choose` chooses from.
- `PluginHarness`: a plugin loaded through the real loader and migrations, invoked through the real call path,
  as a member (`invoke`) or with a token (`invoke_with_token`).
- Voice (D53): the harness's `ctx.voice` connects through `FakeVoice`. `harness.voice_connection` is the
  `FakeVoiceConnection`, whose `take(n)` reads packets as the player would and whose `tracks` list each
  `FakeTrack` played; `harness.end_track()` and `harness.restart_voice()` run what follows.
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
    FakeButton,
    FakeCategory,
    FakeChannel,
    FakeClient,
    FakeGuild,
    FakeMember,
    FakeMessage,
    FakeRole,
    FakeSelect,
    FakeVoiceChannel,
)
from teabot.testing.harness import (
    CheckFailed,
    HarnessFactory,
    JobFailed,
    MemberCalls,
    PluginHarness,
    build_harness,
)
from teabot.testing.snapshot import SnapshotCheck, plugin_snapshot
from teabot.testing.voice import FakeTrack, FakeVoice, FakeVoiceConnection

__all__ = [
    "ActionFailed",
    "CheckFailed",
    "FakeButton",
    "FakeCategory",
    "FakeChannel",
    "FakeClient",
    "FakeGuild",
    "FakeMember",
    "FakeMessage",
    "FakeRole",
    "FakeSelect",
    "FakeTrack",
    "FakeVoice",
    "FakeVoiceChannel",
    "FakeVoiceConnection",
    "HarnessFactory",
    "JobFailed",
    "MemberCalls",
    "Planned",
    "PluginHarness",
    "Queued",
    "Refused",
    "SnapshotCheck",
    "build_harness",
    "plugin_snapshot",
]
