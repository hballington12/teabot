#!/usr/bin/env bash
# The ub-mode quality gates, run before a commit: CRAP under 10 (crapper), no structural duplicates at 0.8
# or above (dryer), and no surviving mutants in changed files (mutator). Needs the three tools on PATH
# (github.com/unclebob/crapper, dryer, mutator) and the dev Postgres.
# Usage: scripts/quality.sh [file-or-dir ...]   with no arguments, mutation-tests the files git sees as changed.
set -euo pipefail
cd "$(dirname "$0")/.."
unset VIRTUAL_ENV

crapper --threshold 10 src

dry_report=$(dryer --threshold 0.8 src)
if grep -q '^DUPLICATE' <<<"$dry_report"; then
  echo "$dry_report"
  echo "dryer: duplicates at 0.8 or above" >&2
  exit 1
fi
echo "dryer: no duplicates at 0.8 or above"

# Test databases and roles carry the test process's pid, so mutants run in parallel safely.
tests="uv run -q pytest -q -x -p no:cacheprovider"
if [ "$#" -gt 0 ]; then
  mutator --max-workers 4 --test-command "$tests" "$@"
else
  mutator --max-workers 4 --test-command "$tests" --changed
fi
