# Keeping the single process: the simplest definitive teabot

## Short answer

I would keep one Python process per shard group as teabot's only process model. I would build no plugin sandbox and no per-plugin subprocesses. Most of the costs in `design/process-model.md` come from two separate problems, and each already has a simple answer:

1. **Trust.** Untrusted code inside the process is a risk no in-process measure can close. The design already handles trust per instance (D5, D44, D47). An operator runs code they trust, and the hosted service runs only code the maintainers reviewed at a pinned commit. A stranger's code runs out of process, through the deferred "out-of-process plugins" item. That item should become the single escape hatch for every case that needs a real boundary.
2. **Fault handling.** Since D40, a restart costs almost nothing: jobs, plans, buttons and config live in Postgres. So the right answer to a hung loop, a leak or a crash is to detect it quickly, name the plugin, exit and let the supervisor restart the process. What's missing today is the detection. Dev mode has it, and production has none.

With those two answers, the remaining work is small. Each piece fits the current design:

- a production loop watchdog
- core-enforced timeouts
- memory limits in the template
- one catalogue-wide dependency check in the hub
- a review rule for plugin dependencies
- corrected wording in D5, D33 and D47

## Why the process should not be split

Running each plugin in its own process looks like the obvious fix for all six costs. It would undo most of the six benefits, and it still would not create a security boundary:

- **No real boundary.** A plugin subprocess running as the same user can still read `teabot.env`, `/proc/<pid>/environ` and the Compose environment. Those hold the Discord token, the `teabot_app` password and the owner password. A real boundary needs a container or a seccomp sandbox per plugin, with its own filesystem and its own credentials. That is a hosting platform, and it is far more than a bot framework needs.
- **Plugins lose the shared cache and direct calls.** Every `ctx.guild` read and every Discord call would go over IPC. That IPC protocol would become a second SDK to version under D45.
- **Transactions get harder.** Today `tx.schedule(...)` and a plugin's writes commit together on one connection (D30). Across processes this needs either a database connection per plugin process or a distributed outbox.
- **Tests and production diverge.** `teabot.testing` loads plugins through the real loader. A split would add a transport layer that the harness either fakes, and so stops testing, or reproduces in full.
- **Self-hosting gets heavier.** About 150 MB per Python process multiplied by the number of plugins hurts the long tail of small instances, which D43 is built around.

## What to do about each cost

| Cost | Answer | Status |
|---|---|---|
| No security boundary | State the in-process trust model plainly, review the hosted catalogue's dependencies, and keep out-of-process plugins as the boundary | design wording plus a hub rule |
| A blocked event loop | A production watchdog that names the plugin and exits past a hard limit | new, small |
| Leaks and C-extension crashes | Memory limits in the template, then a restart. Native dependencies get extra review | template plus a hub rule |
| One dependency environment | Plugins declare wide ranges and use what the SDK provides. Hub CI resolves the whole catalogue together | hub CI |
| Every update restarts everything | Accept it, and keep restarts short. Rolling restarts stay with shard clusters | already deferred |
| No per-plugin limits | The D47 quotas are per-server counts the core already sees. Per-plugin CPU and memory caps are dropped as a requirement | design wording |
| One core for compute | An authoring rule, which the watchdog enforces. Heavy compute uses the escape hatch | design wording |

### 1. Security: write the trust model down, and close the one gap

- **D5 should say what "no sandbox" means in practice.** A loaded plugin holds every right the process holds. That covers the Discord token, the `teabot_app` login (core tables, token hashes, the audit trail) and, while migrations run, the owner login, which row-level security does not apply to (`src/teabot/db/migrate.py`, around line 357). Row-level security and `teabot check` catch mistakes. Review is what stops misuse. The design already says this in general terms. `process-model.md` shows that it should be said this concretely.
- **I considered taking the owner password out of the running process and decided against it.** Migrations would move to a separate `teabot migrate` step, as a one-shot Compose service or a systemd `ExecStartPre`. The gain is small, for three reasons:
    - The Discord token and the `teabot_app` password stay in the process either way.
    - Migration discovery imports plugin packages through their entry points, so plugin code would run in the migrate step too.
    - Separating the credentials properly would need a second env file and a second system user.

    The complexity buys hardening that is not a boundary, so I would leave `teabot run` as it is.
- **The real gap is dependencies.** D51's hub review reads the plugin's own code at a pinned commit. Its transitive dependencies are unreviewed code that runs in the same process, and on the hosted service that process serves every guild. The rule I'd add for hub listings, applied strictly for the hosted catalogue:
    - A listing may use only dependencies already in teabot's own lock, plus an allowlist kept in the hub repo.
    - Adding a new dependency to that allowlist is its own reviewed pull request.
    - Native extensions get extra scrutiny, because they are also the crash risk in section 3.

    This also shrinks the dependency-conflict problem in section 4.
- **Incident path.** Add a short runbook: reset the bot token in the developer portal, rotate the database passwords with `teabot init`, then block the plugin with `TEABOT_DISABLED_PLUGINS` and delist it. The hosted service is run by the maintainers, so blocking a plugin there is immediate.

### 2. A blocked event loop: detect it in production

D33 relies on asyncio's debug mode, which runs only in dev mode (`src/teabot/app.py:321`). Production has nothing. I'd add one small stdlib-only watchdog to the runtime:

- A heartbeat task in the loop updates a timestamp every 0.5 s.
- A daemon thread checks that timestamp:
    - When the heartbeat is more than about 1 s late (the soft limit), it takes the loop thread's frame from `sys._current_frames()`. It walks the stack to the first frame whose module belongs to a loaded plugin package. The loader already knows each plugin's package. It then logs `event loop blocked` with the plugin id, the file and the line.
    - Past a hard limit (a setting, 30 s by default), it logs the same and calls `os._exit(1)`. systemd or Compose restarts the process. Jobs are reclaimed after their lease, and buttons keep working because no state is held in memory (D31, D32).
- It does not disable plugins on its own. The log names the culprit, and the operator blocks it with `TEABOT_DISABLED_PLUGINS`. If restart loops caused by one plugin ever happen in practice, an automatic `failed: blocked the event loop` status can be added later. It would reuse the existing status reasons of D14.

The core should also put `asyncio.timeout` around every action `run`, job handler and event hook, with limits set as settings. This catches coroutines that never finish, which the watchdog cannot see because they do not block the loop. A timed-out job goes through the existing retry and back-off. A timed-out action returns an error through the normal refusal path.

### 3. Leaks and crashes: limit memory and restart

- The template should set `mem_limit` in `compose.yaml` and `MemoryMax=` in the bare-metal unit. A leaking process is then killed and restarted before it starves Postgres on the same machine.
- `/healthz` should report the process's RSS, so the deploy script and the operator can see growth.
- A crash in a C extension is handled the same way. The dependency rule in section 1 reduces how often it can happen.
- Attributing memory to each plugin with `tracemalloc` costs too much to run all the time, so I would not build it.

### 4. One dependency environment: find conflicts at review time

- Hub guidance: a plugin declares lower bounds and avoids upper pins unless it knows of a break. It uses what the SDK already provides, such as `ctx.http` (httpx, D12) and pydantic, and does not bring its own copies.
- Hub CI: on every listing pull request, resolve a synthetic instance that installs the latest teabot and every listed plugin, using `uv lock`. A conflict fails the pull request and names the two plugins. "These two plugins can't both be installed" then shows up at review time, and never during an operator's deploy.
- teabot keeps its own dependency list short and its ranges wide. It mostly does this already (`pyproject.toml`).

### 5. Updates restart everything: accept it, and keep restarts short

- On a small or medium instance, a restart costs a gateway identify per shard and the cache refilling. Command sync is gated by hash, so unchanged guilds cost nothing (D32). D9's rule that migrations must keep the previous release working means two versions can overlap safely.
- A zero-downtime handover belongs with the deferred shard clusters, which already list rolling restarts. In that handover, the new process prepares and waits on the shard locks, and the old process then releases them. I would not build it before that trigger.

### 6. Per-plugin limits: correct the requirement

`process-model.md` says the D47 quotas need per-plugin memory and CPU caps. The deferred-work table in `architecture.md` describes them differently: per-server limits on pending jobs, scheduled jobs, rows per plugin table and actions per minute, with fair queue claims. The core can count every one of those, because every call goes through `registry.invoke` and every job through the queue. The process-model doc should be corrected to match.

What remains cheap and useful is recording how long each action and job takes, by plugin. The audit rows and job rows already exist, so a heavy plugin becomes visible without any new mechanism.

### 7. One core for compute: a rule, enforced by the watchdog

- Discord bot work is mostly I/O. The authoring guide should state two rules. Blocking synchronous libraries go through `asyncio.to_thread`. Sustained CPU-bound work does not belong in a plugin at all.
- The watchdog in section 2 catches a plugin that breaks this rule.
- A plugin that really needs heavy compute is an out-of-process plugin, through the same escape hatch as untrusted code.

## The escape hatch, widened

The deferred "out-of-process plugins" item (signed HTTP actions) currently names one trigger, hosted users who want custom code. I'd widen its trigger to any plugin that needs a boundary the process cannot give:

- an untrusted author
- dependencies that conflict with the catalogue
- sustained CPU work
- a release cadence independent of the bot's

That gives the design one mechanism with one protocol, covering every cost a single process cannot handle. It stays deferred until the first such plugin exists.

## Changes to the design docs

1. **`design/process-model.md`:** add a closing section with the verdict and the answer to each cost, as in the table above, and correct the D47 quota claim.
2. **D5:** list the rights a loaded plugin holds, and add the dependency review rule for hub and hosted listings.
3. **D33:** add the production watchdog and the core-enforced timeouts next to the dev-mode detection.
4. **D43 and the template:** add memory limits for Compose and the bare-metal unit.
5. **D51:** add the catalogue-wide resolve check and the dependency allowlist.
6. **Deferred work:** widen the out-of-process plugins trigger as above, and leave shard clusters and rolling restarts unchanged.

## Order of work

1. The watchdog, the timeouts and RSS in `/healthz`. These are the only runtime code changes, and they close the one real quality gap, which is that production cannot see a stalled loop.
2. The template's memory limits and the incident runbook.
3. The hub's resolve check and dependency allowlist. They are needed before the hosted service opens, and before the hub grows past a handful of plugins.
4. The design-doc wording.

Everything else stays deferred with its current trigger.
