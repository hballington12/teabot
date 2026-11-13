#!/usr/bin/env bash
# One-time setup of a teapot instance on an Ubuntu 24.04 host (D37, D43). Run as root; safe to run again.
#   setup-host.sh <public hostname> <instance repo, e.g. git@github.com:you/teapot-you.git>
# It installs Postgres 16, pgBackRest, git and uv; creates the teapot user, its deploy keys and the database;
# clones the instance into /opt/teapot; runs `teapot init`; adds the Caddy site; and installs the service.
# Backups are set up afterwards with setup-backups.sh, and the bot token with set-discord-token.sh.
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

UV_VERSION=0.9.9
HOST=${1:?usage: setup-host.sh <public hostname> <instance repo>}
REPO=${2:?usage: setup-host.sh <public hostname> <instance repo>}

install_packages() {
    say "packages"
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q postgresql-16 pgbackrest git curl
    if [ "$(uv --version 2>/dev/null | cut -d' ' -f2)" != "$UV_VERSION" ]; then
        curl -LsSf "https://astral.sh/uv/$UV_VERSION/install.sh" | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
    fi
}

create_user() {
    say "teapot user"
    id teapot >/dev/null 2>&1 || useradd --system --home-dir "$APP_HOME" --create-home --shell /usr/sbin/nologin teapot
    install -d -o teapot -g teapot -m 0700 "$APP_HOME/.ssh"
    install -d -o teapot -g teapot -m 0755 "$APP_DIR"
}

# GitHub takes a deploy key for one repository only, so the instance and teapot each get one, and the teapot
# user's git config sends each repository's URL through its own key.
deploy_keys() {
    say "deploy keys"
    local framework
    framework=$(grep -o 'ssh://git@github.com/[^"]*' "$HERE/../../pyproject.toml" | head -1)
    for name in instance framework; do
        [ -f "$APP_HOME/.ssh/$name" ] || as_teapot ssh-keygen -q -t ed25519 -N '' -C "teapot-$name@$HOST" -f "$APP_HOME/.ssh/$name"
    done
    as_teapot sh -c "ssh-keyscan -t ed25519 github.com > '$APP_HOME/.ssh/known_hosts' 2>/dev/null"
    as_teapot tee "$APP_HOME/.ssh/config" >/dev/null <<EOF
Host github-instance github-framework
    HostName github.com
    User git
    IdentitiesOnly yes
Host github-instance
    IdentityFile $APP_HOME/.ssh/instance
Host github-framework
    IdentityFile $APP_HOME/.ssh/framework
EOF
    as_teapot git config --global --replace-all url."git@github-instance:${REPO#*:}".insteadOf "$REPO"
    if [ -n "$framework" ]; then
        as_teapot git config --global --replace-all url."git@github-framework:${framework#ssh://git@github.com/}".insteadOf "$framework"
    fi
    if ! as_teapot git ls-remote -q "$REPO" >/dev/null 2>&1 || { [ -n "$framework" ] && ! as_teapot git ls-remote -q "$framework" >/dev/null 2>&1; }; then
        echo "Add these read-only deploy keys on GitHub, then run this script again:"
        echo "  instance repo ($REPO): $(cat "$APP_HOME/.ssh/instance.pub")"
        [ -n "$framework" ] && echo "  teapot ($framework): $(cat "$APP_HOME/.ssh/framework.pub")"
        exit 2
    fi
}

checkout() {
    say "code in $APP_DIR"
    if [ ! -d "$APP_DIR/.git" ]; then
        as_teapot git clone -q "$REPO" "$APP_DIR"
    fi
    as_teapot sh -c "cd '$APP_DIR' && uv sync --frozen --no-dev -q"
}

setup_postgres() {
    say "postgres"
    local conf pw changed=""
    conf=$(pg_conf_dir)
    changed+=$(install_if_changed "$HERE/postgresql/teapot.conf" "$conf/conf.d/teapot.conf")
    # teapot's roles log in with passwords over the socket. The rule goes after the postgres superuser's peer
    # rule, so `sudo -u postgres psql` keeps working, and before the catch-all `local all all` peer rule.
    awk '/^local[[:space:]]+teapot[[:space:]]/ { next }
        done == 0 && /^local[[:space:]]+all[[:space:]]+all[[:space:]]/ {
            print "local   teapot          all                                     scram-sha-256"; done = 1 }
        { print }' "$conf/pg_hba.conf" > "$conf/pg_hba.conf.new"
    if cmp -s "$conf/pg_hba.conf.new" "$conf/pg_hba.conf"; then
        rm -f "$conf/pg_hba.conf.new"
    else
        install -o postgres -g postgres -m 0640 "$conf/pg_hba.conf.new" "$conf/pg_hba.conf"
        rm -f "$conf/pg_hba.conf.new"
        changed+=changed
    fi
    [ -z "$changed" ] || systemctl restart postgresql
    pw=$(env_value TEAPOT_DB_OWNER_PASSWORD)
    if [ -z "$pw" ]; then
        pw=$(openssl rand -hex 24)
        set_env TEAPOT_DB_OWNER_PASSWORD "$pw"
    fi
    sudo -u postgres psql -q -v ON_ERROR_STOP=1 <<SQL
SELECT 'CREATE ROLE teapot_owner LOGIN CREATEROLE' WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'teapot_owner')\gexec
ALTER ROLE teapot_owner PASSWORD '$pw';
SELECT 'CREATE DATABASE teapot OWNER teapot_owner' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'teapot')\gexec
SQL
}

env_file() {
    say "env file $ENV_FILE"
    install -d -m 0755 /etc/teapot
    if [ ! -f "$ENV_FILE" ]; then
        install -o teapot -g teapot -m 0600 "$APP_DIR/teapot.env.example" "$ENV_FILE"
    fi
    set_env TEAPOT_DB_HOST /var/run/postgresql
    set_env TEAPOT_DB_PORT 5432
    set_env TEAPOT_PUBLIC_URL "https://$HOST"
    set_env TEAPOT_LOG_FORMAT json
}

# `teapot init` creates the runtime roles as the owner. Revoking set_config from PUBLIC needs a superuser, so
# it runs here as postgres, which is what `teapot init --admin-user` would do (D9, S1).
init_database() {
    say "teapot init"
    as_teapot "$APP_DIR/.venv/bin/teapot" init --env-file "$ENV_FILE" | grep -v 'set_config' || true
    sudo -u postgres psql -q -d teapot -v ON_ERROR_STOP=1 <<'SQL'
REVOKE EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION pg_catalog.set_config(text, text, boolean) TO teapot_app, teapot_owner;
SQL
}

# Every site on the host shares one Caddy: validate the whole config, reload rather than restart, and put the
# previous files back if validation fails.
setup_caddy() {
    say "caddy site $HOST"
    local main=/etc/caddy/Caddyfile site=/etc/caddy/teapot.caddy stamp
    stamp=$(date +%Y%m%d%H%M%S)
    cp "$main" "$main.bak-$stamp"
    [ -f "$site" ] && cp "$site" "$site.bak-$stamp"
    sed "s/teapot.example.org/$HOST/" "$HERE/teapot.caddy" > "$site"
    grep -qx 'import teapot.caddy' "$main" || printf '\nimport teapot.caddy\n' >> "$main"
    if ! caddy validate --config "$main" --adapter caddyfile >/dev/null 2>&1; then
        cp "$main.bak-$stamp" "$main"
        if [ -f "$site.bak-$stamp" ]; then cp "$site.bak-$stamp" "$site"; else rm -f "$site"; fi
        die "the Caddy config did not validate; the previous files are back"
    fi
    systemctl reload caddy
}

install_service() {
    say "systemd unit"
    install_if_changed "$HERE/teapot.service" /etc/systemd/system/teapot.service >/dev/null
    systemctl daemon-reload
    systemctl enable -q teapot
    if [ -n "$(env_value TEAPOT_DISCORD_TOKEN)" ]; then
        systemctl restart teapot
    else
        echo "No bot token yet: run set-discord-token.sh, which starts the bot."
    fi
}

need_root
install_packages
create_user
deploy_keys
checkout
env_file
setup_postgres
init_database
setup_caddy
install_service
say "done"
