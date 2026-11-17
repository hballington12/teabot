# design

- For contributors to teabot itself. The documentation site, built from `docs/`, does not include these.
- `design.md`: the numbered design decisions, such as D21, with their reasons. The code's comments cite them.
- `architecture.md`: how teabot is built: the plugin lifecycle, data, processes, the queue, tokens, the front doors, and the deferred work.
- `process-model.md`: the case for and against running the gateway, the core and every plugin in one Python process.
- `process-model-suggestion.md`: a plan for keeping the single process, answering each of its costs.
- `member-directory.md`: a design for keeping every server's members and their history, for admins, AI assistants and plugins to query.
- `server-permissions.md`: a design for listing every channel's permissions, and seeing the server as a set of roles does.
- `spikes.md`: the experiments that settled open technical questions, with their evidence.
- `glossary.md`: the terms the design and the code use.
