#!/usr/bin/env bash
# Set up and start this teabot instance with Docker Compose: ./setup.sh
#
# It asks for the Discord bot token, writes .env and teabot.env, builds and starts the bot and Postgres, creates
# the database roles, and prints the link that invites the bot to a server. It can be run again after a
# failure: files that exist are kept, and each step is safe to repeat.
set -euo pipefail
cd "$(dirname "$0")"

VOLUME=teabot_teabot-pgdata

say() { printf '\n==> %s\n' "$*"; }
fail() { printf 'setup.sh: %s\n' "$*" >&2; exit 1; }

check_docker() {
    command -v docker >/dev/null || fail "Docker is not installed. Install Docker, with Compose, first."
    docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is missing: 'docker compose version' failed."
    docker info >/dev/null 2>&1 || fail "cannot reach Docker. Start it, or on Linux add yourself to the docker group:
    sudo usermod -aG docker \$USER   (then log out and in again)"
}

random_hex() { head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; }

write_compose_env() {
    if [ -f .env ]; then
        echo ".env exists; keeping it."
        return
    fi
    if docker volume inspect "$VOLUME" >/dev/null 2>&1; then
        fail "the database volume $VOLUME exists but .env is missing.
A new password would lock teabot out of its database. Restore the old .env, or, if the database holds
nothing you want, delete it with 'docker compose down -v'."
    fi
    umask 077
    printf 'TEABOT_DB_OWNER_PASSWORD=%s\nTEABOT_UID=%s\nTEABOT_GID=%s\n' "$(random_hex)" "$(id -u)" "$(id -g)" > .env
    echo "wrote .env"
}

set_token() {
    local token=$1 file=teabot.env tmp
    tmp=$(mktemp teabot.env.XXXXXX)
    awk -v token="$token" '/^TEABOT_DISCORD_TOKEN=/ { print "TEABOT_DISCORD_TOKEN=" token; next } { print }' "$file" > "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$file"
}

write_teabot_env() {
    if [ ! -f teabot.env ]; then
        cp teabot.env.example teabot.env
        chmod 600 teabot.env
        echo "wrote teabot.env"
    fi
    if grep -q '^TEABOT_DISCORD_TOKEN=.' teabot.env; then
        echo "teabot.env has a bot token; keeping it."
        return
    fi
    local token
    read -rsp "Paste your Discord bot token (it is not shown): " token
    echo
    [ -n "$token" ] || fail "no token given."
    set_token "$token"
}

wait_healthy() {
    local tries=90 port
    port=$(sed -n 's/^TEABOT_HTTP_PORT=//p' .env | tail -n 1)
    port=${port:-8780}
    until curl -sf "http://127.0.0.1:$port/healthz" >/dev/null 2>&1; do
        tries=$((tries - 1))
        if [ "$tries" -le 0 ]; then
            docker compose logs --tail 30 bot >&2
            fail "teabot did not become healthy within 90 seconds; the log is above. If it says LoginFailure,
the token is wrong: put the right one after TEABOT_DISCORD_TOKEN= in teabot.env and run ./setup.sh again."
        fi
        sleep 1
    done
}

check_docker
if [ ! -d .git ] && command -v git >/dev/null; then
    git init -q && echo "made this folder a git repository"
fi
write_compose_env
write_teabot_env

if [ ! -f uv.lock ]; then
    say "Locking the newest teabot and your plugins"
    docker compose run --rm uv lock -q
fi
say "Building the bot's image"
docker compose build -q bot
say "Starting Postgres"
docker compose up -d --wait postgres
say "Creating the database roles"
init_output=$(docker compose run --rm bot teabot init)
echo "$init_output"
say "Starting teabot"
docker compose up -d bot
wait_healthy

invite=$(printf '%s\n' "$init_output" | grep -o 'https://discord.com/oauth2/authorize[^ ]*' | head -n 1 || true)
say "teabot is running"
if [ -n "$invite" ]; then
    echo "Invite it to your server with this link:"
    echo "    $invite"
fi
