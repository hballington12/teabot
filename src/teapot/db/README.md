# teapot.db

- `naming.py`: role and schema names under one prefix, and the plugin id pattern of D46.
- `types.py`: lazy type aliases for asyncpg, whose classes are generic only in its stubs.
- `pool.py`: the core and plugin pools, role switching, transaction handles and the prepared-statement helpers (D30, spike S1).
- `bootstrap.py`: creates the app and plugins login roles and revokes `set_config` from `PUBLIC`, for `teapot init`.
