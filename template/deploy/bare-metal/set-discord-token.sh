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
set_env TEABOT_DISCORD_TOKEN "$token"
systemctl restart teabot
echo "teabot restarted; check it with: curl -s http://127.0.0.1:8780/healthz"

# A token's first part is the bot's application id in base64, which the invite link needs.
first=${token%%.*}
padding=$(printf '%*s' $(( (4 - ${#first} % 4) % 4 )) '' | tr ' ' '=')
app_id=$(printf '%s%s' "$first" "$padding" | tr '_-' '/+' | base64 -d 2>/dev/null || true)
if [[ "$app_id" =~ ^[0-9]+$ ]]; then
    echo "Invite it to your server with this link:"
    echo "    https://discord.com/oauth2/authorize?client_id=$app_id&scope=bot+applications.commands&permissions=8"
fi
