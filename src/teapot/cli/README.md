# teapot.cli

- `uv run teapot` (D34). Each subcommand works on the database alone, except `run`.
- `init.py`: `teapot init` sets up a new instance: generated secrets and database roles, then the Discord application settings and the invite link (D43).
- `new_plugin.py`: `teapot new-plugin <id>` scaffolds `plugins/<id>/` in an instance, from the templates in `scaffold/` (D44, D45).
- `run.py`: `teapot run` starts a bot process.
- `plugins.py`: `teapot plugins list` shows each plugin's migration version and whether a process has it loaded. `teapot plugins purge <id>` deletes a plugin everywhere after a confirmation prompt, and refuses while a process has it loaded (D7).
