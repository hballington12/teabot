#!/usr/bin/env bash
# Deploy what is on the instance repo's main branch to the host, from the operator's machine (D37):
#   deploy/bare-metal/deploy.sh root@host
# It pulls, syncs the locked dependencies, restarts the bot (which runs pending migrations at start), and
# waits until /healthz on the host's localhost reports ok.
set -euo pipefail
TARGET=${1:?usage: deploy.sh <user@host>}

# shellcheck disable=SC2016  # expanded on the host, not here
ssh "$TARGET" 'set -euo pipefail
    run() { sudo -u teapot -H env UV_CACHE_DIR=/var/lib/teapot/.cache/uv "$@"; }
    run git -C /opt/teapot pull -q --ff-only
    run sh -c "cd /opt/teapot && uv sync --frozen --no-dev --all-packages -q"
    systemctl restart teapot
    if curl -sf --retry 90 --retry-delay 1 --retry-connrefused --retry-all-errors -o /dev/null http://127.0.0.1:8780/healthz; then
        echo "deployed $(run git -C /opt/teapot log --oneline -1)"
        curl -s http://127.0.0.1:8780/healthz; echo
    else
        echo "teapot is not healthy after 90 seconds:" >&2
        curl -s http://127.0.0.1:8780/healthz >&2 || true
        journalctl -u teapot -n 30 --no-pager >&2
        exit 1
    fi'
