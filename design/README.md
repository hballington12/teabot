# design

- For contributors to teabot itself. The documentation site, built from `docs/`, does not include these.
- `design.md`: the numbered design decisions, such as D21, with their reasons. The code's comments cite them.
- `architecture.md`: how teabot is built: the plugin lifecycle, data, processes, the queue, tokens, the front doors, and the deferred work.
- `process-model.md`: the case for and against running the gateway, the core and every plugin in one Python process.
- `process-model-suggestion.md`: a plan for keeping the single process, answering each of its costs.
- `member-directory.md`: the member directory (D55), which keeps every server's members and their history for admins, AI assistants and plugins to query.
- `role-changes.md`: giving members a role, or taking it away, from one member to thousands, in the roles plugin, with what the SDK and the core add for it.
- `server-permissions.md`: listing every channel's permissions, and seeing the server as a set of roles does.
- `glossary.md`: the terms the design and the code use.
