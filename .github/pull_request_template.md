## What and why

<!-- What changes, and why. Name the decision (D-number) it serves, if any. -->

## How it was checked

- [ ] `scripts/check.sh` passes
- [ ] `scripts/quality.sh` passes: CRAP under 10, no duplicates at 0.8, no surviving mutants in changed files

## For a plugin

- [ ] Imports only `teabot.sdk`
- [ ] The README's "External connections" section lists every host contacted (D12)
- [ ] Every table has a `bigint guild_id` column, and no released migration was edited (D9)
- [ ] No Discord or HTTP awaits inside a transaction block, and no blocking I/O (D30, D33)
- [ ] No dynamic SQL built from member input
- [ ] Jobs are safe to run twice (D31)
