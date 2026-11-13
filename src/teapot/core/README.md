# teapot.core

- `processes.py`: the lock connection with shard and plugin advisory locks, reading loaded plugins from `pg_locks`, and the informational process row (D40, spike S2).
- `queue.py`: the durable work queue (D31): `NewJob`, claims with `SKIP LOCKED` and leases, the computed shard filter, retries with back-off.
- `worker.py`: worker pools that run claimed jobs, keep their leases, and sleep until woken by `NOTIFY` or the next due job.
- `maintenance.py`: the daily `core.maintenance` job: prunes finished jobs and stale process rows in batches.
