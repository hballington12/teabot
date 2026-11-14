# teabot.testing

What plugin authors test with, and what the core's own tests use (D45). Install with the `teabot[testing]` extra.

- `fakes.py`: `FakeGuild`, `FakeMember`, `FakeChannel` (records what it is sent) and `FakeClient`. Members in `fetchable` are found only over REST, as an uncached member is (D18).
- `harness.py`: `PluginHarness`. It loads a plugin through the real loader and migrations, enables it in a fake server whose first member has Administrator, and invokes actions through the real call path, permissions and audit included.
- `__init__.py` also exports what `invoke` raises and returns besides an output: `Refused`, `ActionFailed`, `Planned` and `Queued`. A plugin's tests import only `teabot.sdk` and `teabot.testing`.
- `fixtures.py`: pytest fixtures against a real Postgres: `admin`, `naming`, `pools`, `owner_login` and `teabot_harness`. Enable them with `pytest_plugins = ["teabot.testing.fixtures"]`.
- `cleanup.py`: per-run database and role names, and dropping what killed test runs left behind.
