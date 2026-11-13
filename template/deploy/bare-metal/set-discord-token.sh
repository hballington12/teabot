#!/usr/bin/env bash
# Put the bot's Discord token into the env file and (re)start the bot. Run as root on the host.
# The token is read from the terminal, so it never reaches a command line, shell history or git.
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

need_root
[ -f "$ENV_FILE" ] || die "$ENV_FILE is missing; run setup-host.sh first"
read -r -s -p "Discord bot token: " token
echo
[ -n "$token" ] || die "no token given"
set_env TEAPOT_DISCORD_TOKEN "$token"
systemctl restart teapot
echo "teapot restarted; check it with: curl -s http://127.0.0.1:8780/healthz"
