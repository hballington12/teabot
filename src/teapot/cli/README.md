# teapot.cli

- `uv run teapot` (D34). Each subcommand works on the database alone, except `run`.
- `init.py`: `teapot init` sets up a new instance: roles, database, generated secrets (D43).
- `run.py`: `teapot run` starts a bot process.
- `plugins.py`: `teapot plugins list` shows each plugin's migration version and whether a process has it loaded. `teapot plugins purge <id>` deletes a plugin everywhere after a confirmation prompt, and refuses while a process has it loaded (D7).
