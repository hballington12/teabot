# teapot.core

- `processes.py`: the lock connection with shard and plugin advisory locks, reading loaded plugins from `pg_locks`, and the informational process row (D40, spike S2).
- `queue.py`: the durable work queue (D31): `NewJob`, claims with `SKIP LOCKED` and leases, the computed shard filter, retries with back-off.
- `worker.py`: worker pools that run claimed jobs, keep their leases, and sleep until woken by `NOTIFY` or the next due job.
- `maintenance.py`: the daily `core.maintenance` job: prunes finished jobs and stale process rows in batches.
- `loader.py`: the plugin loader (D14, D46): entry points or a given list, unique ids, disabled plugins, plugin locks, migrations and setup, with a status and reason for every plugin.
- `config.py`: per-server plugin config (D8, D10), validated through the plugin's current model, with a `ConfigError` naming plugin and server when stored config no longer validates.
- `registry.py`: the action registry and its one call path (D1, D18, D19, D24): server, enabled plugin, config, input, live permissions, audit, run, outcome.
- `command_sync.py`: per-server command sync (D32). Admin commands are global; a plugin's group is a guild command only where it is enabled. `sync_commands` jobs compare a hash with `core.command_sync` and save it only once Discord accepts the overwrite. Startup queues only what changed.
- `lifecycle.py`: plugin purge (D7). It takes the plugin's lock exclusively and refuses while any process has the plugin loaded. It shows the rows it will delete and asks first. One transaction then drops the schema as the plugin's role, drops the role, deletes the plugin's core rows, queues command syncs and audits the purge for each server and the instance. It needs no plugin code.
- `audit.py`: the audit log (D24): started and finished change rows with their post queued in the same transaction, one row per lookup in the day-partitioned reads table, posts to the log channel, and retention.
