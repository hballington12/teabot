# teapot.adapters

- The front doors over the action registry (D1). Each one turns its own request format into a registry call.
- `schema.py`: the schema builder (D29). An input model becomes Discord command JSON (one group per plugin, a subcommand per action, required options first, `LongText` fields left to a modal) and an MCP tool schema.
