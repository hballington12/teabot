# Glossary

Domain terms as teapot's code and docs use them. Decision numbers point at the [README](../README.md).

- **Action.** One operation a plugin offers, with a typed input, a risk and a required permission. Slash commands, MCP tools and service routes are front doors onto actions (D1).
- **Apply.** The second call of a destructive action, with the plan's confirm value, which runs the change as a job (D21).
- **Core.** The framework itself, as opposed to plugins. Its tables live in the `core` schema and its jobs and roles use the plugin id `core`.
- **Front door.** One way into the action registry: slash commands, the MCP server or the service API (D1).
- **Guild.** Discord's name for a server. The code says guild; the docs say server.
- **Instance.** One running teapot with its own Discord application, database and operator (D35).
- **Job.** A row in `core.jobs`: a handler and a payload with a run time, a state, retries and progress (D31).
- **Lease.** How long a running job stays claimed before another worker may reclaim it. Workers extend it while the handler runs.
- **Lock connection.** A process's one connection outside any pool, holding its shard and plugin advisory locks and its `LISTEN` (D40).
- **Operator.** Whoever runs an instance and installs its plugins (D3, D44).
- **Plan.** The diff a destructive action returns before it changes anything, stored on its audit row (D21).
- **Plugin.** A package with a `teapot.plugins` entry point. It owns a schema `plugin_<id>` and a role `<prefix>_plugin_<id>` (D4, D9).
- **Plugin pool.** The pool logged in as `<prefix>_plugins`, which switches to one plugin's role per use (D30).
- **Process.** One `teapot run`, running some or all shards, recorded informationally in `core.processes` (D40).
- **Ref.** A field holding a Discord ID: `ChannelRef`, `RoleRef` or `MemberRef`. It takes an int or a string of digits, and is a string in JSON (D29).
- **Risk.** `read`, `write` or `destructive`, ordered. Tokens carry a maximum risk (D17).
- **Role prefix.** The start of every database role name, `teapot` by default, so several instances or test runs can share a Postgres server.
- **Scope.** Who a database handle acts as: the core, or one plugin with its role and schema.
- **Shard.** A slice of Discord's gateway connection. A server belongs to shard `(guild_id >> 22) % shard_count` (D40).
- **SDK.** `teapot.sdk`, the only module plugins import. It depends on nothing else in teapot (D45).
- **Surface.** A front door an action appears on: slash, MCP or service. Actions default to all three (D1).
- **Token.** `teapot_<id>_<secret>`, acting as the member who made it, bound to one server (D16, D20).
