# teabot.builtin

- `admin.py`: the core admin plugin, always enabled and with no schema of its own (D3).
    - `/plugins list | enable | disable | config` and `/audit channel | recent`. Each group is a built-in action source, so each is its own top-level command, and its id is reserved.
    - Its actions go through the registry like any plugin's, so they are permission-checked (Manage Server by default) and audited. They work on core tables through core services and never touch `ctx.db`.
    - `/plugins config` with only a plugin shows its settings. With a setting and a value it changes one, validated through the plugin's own config model (D10).
- `tokens.py`: `/tokens create | list | revoke`, slash only. Any member manages their own tokens; listing or revoking others' needs Manage Server. An allow-list must name real actions, and the token is shown once.
- `lookups.py`: `admin.describe_guild`, `admin.find_members` and `admin.job_status`, `READ` actions on every surface, so an LLM or a backend finds ids and follows jobs. `find_members` answers from the member directory once it is ready. Its `sources()` makes the `admin` group, with the other files' actions. Names are `UntrustedText` (D23). A job is visible to its starter, and to others with Manage Server.
- `members.py`: `admin.members` and `admin.member_history`, the member directory's tools (D55), for MCP and the service API, needing Manage Server. Filters are structured, never SQL, and every answer carries the directory's state. Before a server's first copy is done they say how far it has got.
- `permissions.py`: `admin.channels` and `admin.view_as`, computed from the cache with Discord's permission algorithm, for MCP and the service API, needing Manage Server.
- `config.py`: `AdminConfig`, the core's own per-server settings, stored like any plugin's config. It holds the log channel that audit posts go to (D24).
