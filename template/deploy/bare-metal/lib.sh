# Shared by the bare-metal scripts. Sourced, never run.
# shellcheck shell=bash

# Used by the scripts that source this file.
# shellcheck disable=SC2034
ENV_FILE=/etc/teabot/teabot.env
# shellcheck disable=SC2034
APP_DIR=/opt/teabot
APP_HOME=/var/lib/teabot
# shellcheck disable=SC2034
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '\n== %s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }
need_root() { [ "$(id -u)" -eq 0 ] || die "run this as root"; }

# Set NAME=VALUE in the env file, replacing the line if it is there. The value never reaches the command line
# of another process, so it does not show in `ps`.
set_env() {
    local name=$1 value=$2 tmp
    tmp=$(mktemp)
    NAME="$name" VALUE="$value" awk 'BEGIN { n = ENVIRON["NAME"]; v = ENVIRON["VALUE"]; done = 0 }
        index($0, n "=") == 1 { print n "=" v; done = 1; next } { print }
        END { if (!done) print n "=" v }' "$ENV_FILE" > "$tmp"
    cat "$tmp" > "$ENV_FILE"
    rm -f "$tmp"
}

env_value() { grep -m1 "^$1=" "$ENV_FILE" 2>/dev/null | cut -d= -f2-; }

# Install SRC as DEST with MODE if the contents differ. Prints "changed" when it wrote the file.
install_if_changed() {
    local src=$1 dest=$2 mode=${3:-0644}
    if [ -f "$dest" ] && cmp -s "$src" "$dest"; then
        return 0
    fi
    install -m "$mode" "$src" "$dest"
    echo changed
}

as_teabot() { sudo -u teabot -H env UV_CACHE_DIR="$APP_HOME/.cache/uv" "$@"; }

# The cluster's data and config directories, from pg_lsclusters: "16 main" -> /var/lib/postgresql/16/main.
pg_version() { pg_lsclusters --no-header | awk 'NR == 1 { print $1 }'; }
pg_conf_dir() { echo "/etc/postgresql/$(pg_version)/main"; }
pg_data_dir() { echo "/var/lib/postgresql/$(pg_version)/main"; }
