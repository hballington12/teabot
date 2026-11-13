# teapot.builtin

- `admin.py`: the core admin plugin, always enabled and with no schema of its own (D3).
    - `/plugins list | enable | disable | config` and `/audit channel | recent`. Each group is a built-in action source, so each is its own top-level command, and its id is reserved.
    - Its actions go through the registry like any plugin's, so they are permission-checked (Manage Server by default) and audited. They work on core tables through core services and never touch `ctx.db`.
    - `/plugins config` with only a plugin shows its settings. With a setting and a value it changes one, validated through the plugin's own config model (D10).
- `config.py`: `AdminConfig`, the core's own per-server settings, stored like any plugin's config. It holds the log channel that audit posts go to (D24).
