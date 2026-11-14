#!/usr/bin/env bash
# Continuous backups of the teabot database to an S3-compatible bucket with pgBackRest. Run as root
# after setup-host.sh; safe to run again.
#   setup-backups.sh <bucket> <region, e.g. lon1>
# It asks for the bucket's access key and secret on the terminal, so they never reach a command line or a
# file in git. The encryption passphrase is generated once: keep a copy somewhere safe, such as a password
# manager, because without it no backup can be restored.
set -euo pipefail
# shellcheck source=lib.sh
source "$(dirname "$0")/lib.sh"

BUCKET=${1:?usage: setup-backups.sh <bucket> <region>}
REGION=${2:?usage: setup-backups.sh <bucket> <region>}
SECRETS=/etc/pgbackrest/conf.d/secrets.conf

write_config() {
    say "pgbackrest config"
    install -d -m 0750 -o root -g postgres /etc/pgbackrest /etc/pgbackrest/conf.d
    sed -e "s|@BUCKET@|$BUCKET|" -e "s|@REGION@|$REGION|" -e "s|@PGDATA@|$(pg_data_dir)|" \
        "$HERE/pgbackrest/pgbackrest.conf" > /etc/pgbackrest/pgbackrest.conf
    chmod 0640 /etc/pgbackrest/pgbackrest.conf
    chgrp postgres /etc/pgbackrest/pgbackrest.conf
}

write_secrets() {
    say "access key"
    local key secret pass
    if [ -f "$SECRETS" ] && [ "${REPLACE_KEYS:-}" != 1 ]; then
        echo "keeping the keys in $SECRETS (REPLACE_KEYS=1 asks again)"
        return
    fi
    read -r -p "access key id: " key
    read -r -s -p "secret key: " secret
    echo
    pass=$(grep -m1 '^repo1-cipher-pass=' "$SECRETS" 2>/dev/null | cut -d= -f2- || true)
    [ -n "$pass" ] || pass=$(openssl rand -base64 48 | tr -d '\n')
    umask 0027
    printf '[global]\nrepo1-s3-key=%s\nrepo1-s3-key-secret=%s\nrepo1-cipher-pass=%s\n' "$key" "$secret" "$pass" > "$SECRETS"
    chgrp postgres "$SECRETS"
    echo "The encryption passphrase is in $SECRETS. Copy it somewhere safe now."
}

start_archiving() {
    say "stanza and WAL archiving"
    sudo -u postgres pgbackrest --stanza=teabot stanza-create
    if [ -n "$(install_if_changed "$HERE/postgresql/teabot-archive.conf" "$(pg_conf_dir)/conf.d/teabot-archive.conf")" ]; then
        systemctl restart postgresql
        systemctl try-restart teabot
    fi
    sudo -u postgres pgbackrest --stanza=teabot check
}

schedule() {
    say "first full backup and the timers"
    for unit in pgbackrest-backup@.service pgbackrest-full.timer pgbackrest-diff.timer; do
        install_if_changed "$HERE/pgbackrest/$unit" "/etc/systemd/system/$unit" >/dev/null
    done
    systemctl daemon-reload
    systemctl enable -q --now pgbackrest-full.timer pgbackrest-diff.timer
    sudo -u postgres pgbackrest --stanza=teabot info | grep -q 'full backup' \
        || systemctl start pgbackrest-backup@full.service
    sudo -u postgres pgbackrest --stanza=teabot info
}

need_root
write_config
write_secrets
start_archiving
schedule
say "done"
