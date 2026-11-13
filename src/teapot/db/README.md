# teapot.db

- `naming.py`: role and schema names under one prefix, and the plugin id pattern of D46.
- `types.py`: lazy type aliases for asyncpg, whose classes are generic only in its stubs.
- `pool.py`: the core and plugin pools, role switching, transaction handles and the prepared-statement helpers (D30, spike S1).
- `bootstrap.py`: creates the app and plugins login roles and revokes `set_config` from `PUBLIC`, for `teapot init`.
- `lockkeys.py`: advisory lock namespaces and the stable plugin key of spike S2.
- `migrate.py`: the migration runner (D9, D15): core first, then each plugin as its own role, one transaction per file, with checksums, the `guild_id` check and failure isolation.
- `migrations/`: the core's numbered SQL files for the `core` schema.
