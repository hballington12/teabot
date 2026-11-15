# The single process

A teabot service runs one Python process per shard group: the Discord gateway, the core and every plugin share one event loop, one environment and one memory space. These are the reasons for and against that.

## For a single process

- **Simple to run.** There is one image, one environment and one log stream. `docker compose up` gives a self-hoster everything, which matters for the long tail of small services.
- **Fast and cheap.** A plugin reads discord.py's member cache and calls Discord directly, with no hop in between. One process costs one Python's memory, about 150 to 250 MB, whatever the number of plugins.
- **One gateway, plainly shared.** Discord sends each shard's events over one connection. In one process, every plugin hears them with no forwarding.
- **Simple transactions.** A plugin's writes, its queued jobs and its outbox posts commit on one connection, in one block.
- **Tests match production.** The harness loads plugins exactly as the bot does, so a passing test means the same code path.
- **It's the RuneLite model.** RuneLite runs every hub plugin in one JVM, and review is its only boundary.

## Against it

- **No security boundary inside the process.** A plugin can do anything the process can:
    - read `os.environ`, which holds the bot token and the database owner's password
    - reach the core's pool and other plugins' objects through Python itself
    - patch teabot's code while it runs

    `teabot check` catches the obvious cases and row-level security limits plugin SQL, but neither stops deliberate misuse. RuneLite's stakes are one user's client. Ours are every server on a service, so a malicious plugin that gets past review on the main service reaches all of its guilds.
- **No fault isolation.**
    - A plugin that blocks the event loop, with a slow loop or a synchronous call, stalls every server and plugin until it returns.
    - A memory leak, or a crash in a C extension, takes the whole service down.
    - Failed jobs retry, but none of that protects against a hung loop.
- **One dependency environment.** Two plugins needing incompatible versions of a library can't both be installed. Every plugin's dependencies also constrain teabot's own. This gets worse as the hub grows.
- **Every update restarts everything.** Updating one plugin restarts the bot, which reconnects the gateway for every server. Shard clusters with rolling restarts (D40) soften this, but each process still holds all plugins.
- **No per-plugin limits.** There's no way to cap one plugin's memory or CPU. The hosted service's quotas (D47) are per-server counts of jobs, rows and actions, which the core can keep, so they do not need these caps.
- **One core for compute.** Python's global interpreter lock means a CPU-heavy plugin competes with the gateway for the same core. Scaling is only by shard groups, each carrying every plugin.

## The verdict

teabot keeps the single process. Splitting plugins into processes would cost the shared cache, direct Discord calls and the shared test path, and add a second SDK in its IPC protocol, while a same-user subprocess still reads the secrets. A real boundary would need a container per plugin. Each cost above has a smaller answer instead, set out in `process-model-suggestion.md`:

| Cost | Answer |
|---|---|
| No security boundary | The trust model in D5, review of every dependency change to the hosted lock, the hub's allowlist (D51), and out-of-process plugins for unreviewed code on the hosted service |
| No fault isolation | The watchdog and its `faulthandler` limit, timeouts for actions and jobs (D33, D31), the queue failing a job that stops the process on every attempt, and a memory cap (D43) |
| One dependency environment | Wide ranges, the SDK's own libraries, and a nightly resolve of the whole catalogue (D51) |
| Every update restarts everything | Short restarts, and rolling restarts with the deferred shard clusters |
| No per-plugin limits | Per-server quotas the core counts, and `duration_ms` in the logs |
| One core for compute | `asyncio.to_thread`, and a service of the plugin's own for heavy work, called through `ctx.http` |
