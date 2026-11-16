#!/usr/bin/env bash
# Put the application's OAuth2 client secret into the env file and restart the bot, which turns on the dashboard
# when TEABOT_PUBLIC_URL is set too. Run as root on the host. The secret is read from the terminal, so it never
# reaches a command line, shell history or git.
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

need_root
[ -f "$ENV_FILE" ] || die "$ENV_FILE is missing; run setup-host.sh first"
read -r -s -p "OAuth2 client secret: " secret
echo
[ -n "$secret" ] || die "no secret given"
set_env TEABOT_DISCORD_CLIENT_SECRET "$secret"
systemctl restart teabot
if curl -sf --retry 60 --retry-delay 1 --retry-connrefused --retry-all-errors -o /dev/null http://127.0.0.1:8780/healthz; then
    public=$(grep -E '^TEABOT_PUBLIC_URL=' "$ENV_FILE" | cut -d= -f2-)
    if [ -n "$public" ]; then
        echo "teabot restarted. The dashboard is at ${public%/}/dashboard"
    else
        echo "teabot restarted. Set TEABOT_PUBLIC_URL too, or there is no dashboard."
    fi
else
    die "teabot is not healthy after a minute; see journalctl -u teabot"
fi
