# Keeping the single process: the simplest definitive teabot

## Short answer

teabot keeps one Python process per shard group as its only process model, with no plugin sandbox and no per-plugin subprocesses. Most of the costs in `process-model.md` come from two separate problems, and each has a simple answer:

1. **Trust.** Untrusted code inside the process is a risk no in-process measure can close. The design handles trust per instance (D5, D44, D47). An operator runs code they trust, and the hosted service runs only code the maintainers reviewed at a pinned commit, with every dependency change to its lock reviewed too. A stranger's code on the hosted service runs out of process, through the deferred "out-of-process plugins" item.
2. **Faults.** Since D40, a restart costs almost nothing: jobs, plans, buttons and config live in Postgres. So the answer to a hung loop, a leak or a crash is to detect it quickly, name the plugin, exit and let the supervisor restart the process. Two things are missing today. Production cannot see a stalled loop, since only dev mode can. And a job that kills the process is claimed again after every restart, so one bad job becomes an endless crash loop.

The work that follows is small, and each piece fits the current design:

- a cap on attempts when the queue reclaims a job from a dead process
- a production watchdog with a hard limit that holds even when a C call holds the GIL
- timeouts declared per action and per job, with core defaults
- memory figures in `/healthz`, durations in the logs, and memory limits in the template
- review of every dependency change to the hosted instance's lock, with a hub check of each listing's dependencies
- an incident runbook that actually contains a plugin
- corrected wording in D5, D13, D33, D51 and `process-model.md`

## Why the process is not split

Running each plugin in its own process looks like the obvious fix for all six costs. It would undo most of the six benefits, and it still would not create a security boundary:

- **Plugins lose the shared cache and direct calls.** Every `ctx.guild` read and every Discord call would go over IPC, and that IPC protocol would become a second SDK to version under D45. This is the main cost.
- **No real boundary.** A plugin subprocess running as the same user can still read `teabot.env`, `/proc/<pid>/environ` and the Compose environment, which hold the Discord token and the database passwords. A real boundary needs a container or a seccomp sandbox per plugin, with its own filesystem and credentials. That is a hosting platform, far more than a bot framework needs.
- **Tests and production diverge.** `teabot.testing` loads plugins through the real loader. A split would add a transport layer that the harness either fakes, and so stops testing, or reproduces in full.
- **Self-hosting gets heavier.** Each worker costs about 40 to 60 MB without discord.py's cache, multiplied by the number of plugins, which hurts the long tail of small instances that D43 is built around.

Transactions are not a reason: a plugin subprocess could hold its own `teabot_plugins` pool, and `tx.schedule` is a SQL function in the plugin's schema, so its jobs and writes would still commit together.

## What to do about each cost

| Cost | Answer | Status |
|---|---|---|
| No security boundary | State the in-process trust model plainly, review every dependency change to the hosted lock, and keep out-of-process plugins for untrusted code on the hosted service | design wording, a review rule, a hub check |
| A blocked event loop | A watchdog that names the plugin, and a hard limit through `faulthandler` that exits | new, small |
| A job that kills the process | Cap attempts on the reclaim path, so the job fails instead of running again | new, small |
| A coroutine that never finishes | Timeouts declared per action and per job | new, small |
| Leaks and C-extension crashes | Memory limits in the template, then a restart. Native dependencies get extra review | template plus a review rule |
| One dependency environment | Plugins declare wide ranges and use what the SDK provides. A nightly resolve of the whole catalogue warns of clashes | hub guidance and CI |
| Every update restarts everything | Accept it, and keep restarts short. Rolling restarts stay with shard clusters | already deferred |
| No per-plugin limits | The D47 quotas are per-server counts, not per-plugin CPU and memory caps. Durations in the logs show a heavy plugin | design wording plus log fields |
| One core for compute | An authoring rule, which the watchdog enforces. Heavy compute goes to a service of the plugin's own | design wording |

### 1. Security: write the trust model down, and review what actually runs

- **D5 says what "no sandbox" means in practice.** A loaded plugin holds every right the process holds, for the life of the process:
    - the Discord token
    - the `teabot_app` login: core tables, token hashes, the audit trail
    - the owner password, which `Settings` keeps and which Compose puts in the environment. The owner role is exempt from row-level security, since the tables are not set to `FORCE` (`src/teabot/db/migrate.py`).

    Plugin import code also runs while the owner connection is open, since `_load_plugins` opens it before `discover()`. Row-level security and `teabot check` catch mistakes. Review is what stops misuse.
- **Migrations stay inside `teabot run`.** A separate `teabot migrate` step would take the owner password out of the long-running process. The gain does not justify the cost, for three reasons:
    - The Discord token alone already reaches every guild, and it stays in the process either way.
    - Migration discovery imports plugin packages, so plugin code runs in that step too.
    - Separating the credentials properly would need a second env file and a second system user.
- **The binding control is the hosted instance's lock.** The hub's review reads a plugin's own code at a pinned commit, while its transitive dependencies run in the same process. A list of package names reviews no versions, and each self-hoster's `uv.lock` picks versions the hub never saw. So:
    - **The hard rule:** every change to the hosted instance's hash-pinned `uv.lock` is a reviewed diff, dependencies included.
    - **The hub check:** each listing's resolved dependency closure, transitive packages included, is checked against an allowlist kept in the hub repo. Adding a package to the allowlist is its own reviewed pull request.
    - **Native extensions** get extra scrutiny, because they are also the crash risk in section 4.
- **The incident runbook contains a plugin by uninstalling it.**
    - `TEABOT_DISABLED_PLUGINS` stops a plugin's commands and jobs, but the loader still imports every installed plugin. Blocking does not stop top-level code, so it contains nothing malicious, and it cannot help with a hang at import time. The loader therefore checks the disabled list before `ep.load()`, which is easy because the entry point's name is the plugin id.
    - The steps:
        1. Remove the plugin from the lock and redeploy, and delist it from the hub.
        2. Reset the bot token in the developer portal.
        3. Rotate the database passwords. `teabot init` only fills missing passwords, so it gains a `--rotate` option that replaces the app and plugins passwords and runs `ALTER ROLE`. The owner password under Compose is the `POSTGRES_PASSWORD` the volume was made with, so rotating it is an `ALTER ROLE` as the owner, then the new value in `.env`.

### 2. A job that kills the process: fail it instead of running it again

The queue reclaims a `running` job whose lease has expired (`SELECT_DUE` in `src/teabot/core/queue.py`) without comparing `attempts` with `max_attempts`. Only `Queue.fail()` marks a job `failed`, and `fail()` never runs when the process dies. So a job that blocks the loop, leaks memory or segfaults follows this loop:

1. The watchdog or the OOM killer stops the process, and the supervisor restarts it.
2. The lease runs out after 60 s.
3. The job is claimed again, and the process dies again.

Event hooks are jobs too, so one bad message handler is enough. Compose's `restart: unless-stopped` and systemd's `Restart=on-failure` repeat it without limit.

The fix: when the claim finds an expired `running` job with `attempts >= max_attempts`, it marks the job `failed` with the error "the process stopped while running it", and does not run it. The job's plugin and handler show in `/admin job_status`, and the log names them.

### 3. A blocked event loop: detect it in production

D33 relies on asyncio's debug mode, which runs only in dev mode (`src/teabot/app.py`). Production has nothing. The runtime gains one small stdlib-only watchdog:

- **A heartbeat task** in the loop runs every 0.5 s. On every tick it calls `faulthandler.dump_traceback_later(hard_limit, exit=True)`, which re-arms the timer.
- **The hard limit** is a setting, 30 s by default. If the loop misses it, `faulthandler`'s own C thread, which needs no GIL, dumps every thread's traceback and exits the process. That holds even while a C extension holds the GIL, which a Python thread cannot see past. The traceback names the plugin's file and line, and systemd or Compose restarts the process.
- **The soft limit** is a Python daemon thread. When the heartbeat is more than about 1 s late, it takes the loop thread's frame from `sys._current_frames()`. It walks to the innermost frame whose module belongs to a plugin package, the one nearest the blocking call. It then logs `event loop blocked` with the plugin id, the file and the line.
- **It starts before `discover()`,** with an allowance for startup, so a plugin that hangs at import time is caught too. It takes the plugin package names from the entry points, since the loader's list of loaded plugins does not exist while imports run.
- **It does not disable plugins on its own.** Repeated deaths of one job end through the cap in section 2. The log names the plugin, and the operator uninstalls or blocks it.

On bare metal, systemd's `Type=notify` with `WatchdogSec=` could add a kill from outside the process. `faulthandler` already covers both deploy paths, so it is not needed.

### 4. A coroutine that never finishes: timeouts per action and per job

The watchdog cannot see a coroutine that awaits forever, since it does not block the loop. A hung job also holds its lease forever, because `_keep_lease` extends it for as long as the coroutine is alive. So the core runs every action and every job inside `asyncio.timeout`:

- The limit is declared per action and per job, with a core default, as a manifest field with a default (D6). One setting for everything would be wrong: a D21 apply waits out Discord's rate limits, so a role change on hundreds of members can rightly take minutes.
- Event hooks are jobs, so two mechanisms cover everything: one for actions and one for jobs.
- A timed-out job goes through the existing retry and back-off. A timed-out action raises `TimeoutError` inside `registry._run`, which the existing handler records as an error and reports through the normal path.

### 5. Leaks and crashes: limit memory, show it, and restart

- The template sets `mem_limit` in `compose.yaml` and `MemoryMax=` in the bare-metal unit. A leaking process is killed and restarted before it starves Postgres on the same machine, and section 2's cap ends a job that keeps causing it.
- `/healthz` reports the process's current resident memory, read from `/proc/self/statm`, so the deploy script and the operator can see growth. Peak memory from `ru_maxrss` only ever rises, so it is not the figure to report.
- A crash in a C extension is handled the same way. The review of native dependencies in section 1 makes it rarer.
- Attributing memory to each plugin with `tracemalloc` costs too much to run all the time, so teabot does not do it.

### 6. One dependency environment: find conflicts early

- **Hub guidance:** a plugin declares lower bounds and avoids upper pins unless it knows of a break. The one required exception is teabot's own range, `teabot>=x,<2`, which D14 requires. A plugin uses what the SDK provides, such as `ctx.http` (httpx, D12) and pydantic, and does not bring its own copies.
- **A nightly resolve:** a scheduled job resolves a synthetic instance that installs the latest teabot and every listed plugin, with `uv lock`. A clash opens an issue naming the plugins involved. It is not a pull-request gate, since an upstream release can break the resolve with no pull request, and the pull request that then failed would belong to an innocent author. It is advice for self-hosters. On the hosted service, the reviewed lock of section 1 decides.
- teabot keeps its own dependency list short and its ranges wide. The upper pins it has, `asyncpg<0.33` and `mcp<3`, each guard a known break.

### 7. Updates restart everything: accept it, and keep restarts short

- On a small or medium instance, a restart costs a gateway identify per shard and the cache refilling. Command sync is gated by hash, so unchanged guilds cost nothing (D32). D9's rule that migrations keep the previous release working means two versions can overlap safely.
- A zero-downtime handover belongs with the deferred shard clusters, which already list rolling restarts. There, the new process prepares and waits on the shard locks, and the old process then releases them. It waits for that trigger.

### 8. Per-plugin limits: correct the requirement

`process-model.md` says the D47 quotas need per-plugin memory and CPU caps. The deferred-work table in `architecture.md` describes them as per-server limits: pending jobs, scheduled jobs, rows per plugin table and actions per minute, with fair queue claims. The core can count the actions and jobs, because every call goes through `registry.invoke` and every job through the queue. Rows per plugin table need SQL counts or triggers, which the quota work adds when it comes.

To make a heavy plugin visible, the existing action and job log lines gain a `duration_ms` field, tagged with the plugin. Neither `core.audit_log` nor `core.jobs` records a duration today, and a column can follow if the logs prove too little.

### 9. One core for compute: a rule, enforced by the watchdog

- Discord bot work is mostly I/O. The authoring guide states two rules. Blocking synchronous libraries go through `asyncio.to_thread`. Sustained CPU-bound work does not belong in a plugin at all.
- The watchdog in section 3 catches a plugin that breaks the rule.
- A plugin that needs heavy compute, its own release cadence, or dependencies that clash with the catalogue runs that part as a service of its own and calls it through `ctx.http`, declared in its External connections (D12). The authoring guide describes the pattern.

## The out-of-process trigger stays narrow

The deferred "out-of-process plugins" item, signed HTTP actions, keeps its one trigger: hosted users who want to run code the maintainers have not reviewed. It is a second SDK, with no shared cache and no `ctx.db`, so it is worth building only for that case. Heavy compute, an independent release cadence and conflicting dependencies are met by section 9's pattern, which costs nothing to support.

## Changes to the design docs

1. **`design/process-model.md`:** add a closing section with the verdict and the answer to each cost, as in the table above, and correct the D47 quota claim.
2. **D5:** list the rights a loaded plugin holds for the life of the process, and add the rule that every dependency change to the hosted lock is reviewed.
3. **D13:** say that the loader skips importing a blocked plugin, and that uninstalling is what contains a harmful one.
4. **D31:** add the attempt cap on the reclaim path, and per-job timeouts.
5. **D33:** add the production watchdog, its `faulthandler` hard limit and the per-action timeouts, next to the dev-mode detection.
6. **D43 and the template:** add memory limits for Compose and the bare-metal unit.
7. **D51:** add the listing closure check against the allowlist, and the nightly catalogue resolve.

## Order of work

1. **The runtime fixes:**
    - cap attempts on the reclaim path
    - the heartbeat, with the `faulthandler` hard limit and the attributed soft-limit log
    - per-action and per-job timeouts with defaults
    - current memory in `/healthz`, and `duration_ms` in the log lines
2. **Operations:**
    - memory limits in the template
    - the loader skipping blocked plugins before import
    - `teabot init --rotate`
    - the incident runbook
3. **Dependencies:**
    - review of the hosted lock's dependency changes
    - the hub's closure check against the allowlist
    - the nightly catalogue resolve
4. **The design-doc wording.**

Everything else stays deferred with its current trigger.
