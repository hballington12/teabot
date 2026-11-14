# teapot.adapters

- The front doors over the action registry (D1). Each one turns its own request format into a registry call.
- `schema.py`: the schema builder (D29). An input model becomes Discord command JSON (one group per plugin, a subcommand per action, required options first, `LongText` fields left to a modal) and an MCP tool schema.
- `interactions.py`: the interaction router (D29, D32): slash commands, `LongText` modals through draft rows any process can finish, ephemeral replies through an action's renderer or the default embed, and refusals. A destructive command's plan is shown with a Confirm button whose custom id holds only the confirm value. A press looks the plan up and calls the action again through the same checks as the other doors, so a button still works after a restart (D21).
- `mcp.py`: actions as MCP tools on the SDK's low-level server (D22, D23, D28).
    - `tools/list` is built for each request from the token: actions offered over MCP, of built-in groups and of plugins enabled in its server, up to its maximum risk and within its allow-list.
    - `tools/call` goes through the one call path. Refusals and failures are `isError` results; an unexpected exception's text stays in the audit log.
    - Annotations come from the risk, and a `WRITE` tool sends `destructiveHint: false`. `UntrustedText` values become `{"untrusted_text": ...}`.
    - Stateless with JSON responses, so any process answers any request. Transport security allows the public host and local hosts only.
- `service_api.py`: `POST /api/v1/actions/<name>` with `{"input": {...}}` (D20), behind the bearer check, as the token's member in its server. Outputs are plain JSON. Refusals answer 404 (no such action here), 403 (the token or member may not), 409 (the server is not ready for it) or 422 (bad input), with the registry's code. An `ActionError` answers 400 with its message; any other failure answers 500, its details kept in the audit log.
