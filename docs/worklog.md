# Work log

Each action taken while building teapot, and why. Newest last. Commits carry the detail; this records the reasons.

## 2026-11-13

- **Rewrote `main` and force-pushed.** The user asked to drop the PR-shaped history; the spike commit lost its "(#43)" suffix and got the local author. Trees were compared identical before the push.
- **WP1.2 settings and logging.** pydantic-settings with `SecretStr` secrets. A test keeps `template/teapot.env.example` in step with the `Settings` fields, so the template cannot drift.
- **Fixed `scripts/check.sh`.** Under `set -e`, `ruff check --fix` failed on unfixable lines before the formatter ran, so long lines were never wrapped. It now formats first and lets the fix step pass.
- **WP1.3 database layer.** Built to spike S1's findings: two login roles, plugin role switching with an explicit `RESET ROLE`, prepared-statement helpers, an explicit `tx`. Role names got a prefix setting because roles are server-wide and tests would otherwise collide with each other and with a dev instance.
- **asyncpg type aliases.** asyncpg's classes are generic only in its stubs, so `asyncpg.Connection[...]` fails at runtime. PEP 695 aliases in `teapot.db.types` are lazy and fix it in one place.
- **WP1.4 migration runner.** Added checksums for applied files, so an edited migration is refused. Corrected D2: bookkeeping tables such as `core.migrations` hold no server data and carry no `guild_id`.
- **WP1.5 locks and process rows.** A typed `Login` replaced loose connection keyword arguments, which strict pyright rejected. Database fixtures moved into the shared `tests/conftest.py` so there is one copy.
- **Installed ub-mode and its tools.** The user asked for ub-mode's principles. crapper, dryer and mutator were installed as editable uv tools under `~/.local/share/ub-tools`, siblings because mutator imports crapper from `../crapper`. `coverage` was added to the dev group so crapper does not pip-install into the uv environment.
- **WP1.6 work queue.** The queue was written before its tests, which broke TDD; crapper scored `claim` at 42. Tests brought every function under CRAP 10. Mutator then found 6 survivors out of 11:
    - notifying only for due jobs was a condition with no effect, so queuing now always notifies, in Python and in `schedule_job`
    - nothing tested that idle or failing workers wait between polls, or that a long job keeps its lease, so tests now do
  The mutation score went from 45.5% to 100%.
- **Added `scripts/quality.sh`, the glossary and this log**, as ub-mode asks.
