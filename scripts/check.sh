#!/usr/bin/env bash
# Run every check CI runs, after applying ruff's safe fixes and formatting.
# Needs the dev Postgres: docker compose -f template/compose.yaml up -d --wait postgres
set -euo pipefail
cd "$(dirname "$0")/.."
unset VIRTUAL_ENV
uv run -q ruff format -q
uv run -q ruff check --fix --exit-zero -q
uv run -q ruff format -q
uv run -q ruff check
uv run -q pyright
uv run -q lint-imports
uv run -q pytest -q "$@"
