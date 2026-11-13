# teapot.testing

What plugin authors test with, and what the core's own tests use (D45). Install with the `teapot[testing]` extra.

- `fakes.py`: `FakeGuild`, `FakeMember`, `FakeChannel` (records what it is sent) and `FakeClient`. Members in `fetchable` are found only over REST, as an uncached member is (D18).
- `harness.py`: `PluginHarness`. It loads a plugin through the real loader and migrations, enables it in a fake server whose first member has Administrator, and invokes actions through the real call path, permissions and audit included.
- `fixtures.py`: pytest fixtures against a real Postgres: `admin`, `naming`, `pools`, `owner_login` and `teapot_harness`. Enable them with `pytest_plugins = ["teapot.testing.fixtures"]`.
- `cleanup.py`: per-run database and role names, and dropping what killed test runs left behind.
