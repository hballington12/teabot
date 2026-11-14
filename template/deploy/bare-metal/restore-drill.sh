#!/usr/bin/env bash
# The restore drill (D37): restore the latest backup into a scratch cluster on another machine and check it
# starts and holds the host's data. Run it from the operator's machine, which needs Docker:
#   deploy/bare-metal/restore-drill.sh root@host
# The bucket's key and the passphrase stream from the host into the container over SSH; they never reach
# this machine's disk, and the container and its data are removed at the end. The restored cluster has WAL
# archiving off, so it can never write to the real repository.
# Just before the drill it writes the time into restore_drill in the cluster's `postgres` maintenance
# database, never teabot's. That row is newer than any backup, so finding it proves archived WAL replays.
set -euo pipefail
TARGET=${1:?usage: restore-drill.sh <user@host>}
NAME=teabot-restore-drill
COMPARE="SELECT (SELECT string_agg(plugin_id || ':' || version, ',' ORDER BY plugin_id, version) FROM core.migrations),
    (SELECT count(*) FROM core.guild_plugins), (SELECT count(*) FROM core.audit_log), (SELECT count(*) FROM core.tokens)"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
cleanup

MARK="CREATE TABLE IF NOT EXISTS restore_drill (at timestamptz NOT NULL);
    INSERT INTO restore_drill VALUES (clock_timestamp()) RETURNING at"

echo "== on the host now"
# shellcheck disable=SC2029  # COMPARE and MARK are meant to expand here
host_state=$(ssh "$TARGET" "sudo -u postgres psql -d teabot -tAc \"$COMPARE\"")
# shellcheck disable=SC2029
marker=$(ssh "$TARGET" "sudo -u postgres psql -qtA -d postgres -c \"$MARK\" && sudo -u postgres psql -qtAc 'SELECT pg_switch_wal()' >/dev/null")
echo "$host_state"
echo "marker written at $marker"

echo "== a scratch container with Postgres 16 and pgBackRest"
docker run -d --name "$NAME" --entrypoint sleep postgres:16 infinity >/dev/null
docker exec "$NAME" sh -c 'apt-get update -qq && apt-get install -y -qq pgbackrest ca-certificates >/dev/null 2>&1'

echo "== the host's pgBackRest config, with the restore path and archiving off"
ssh "$TARGET" "cat /etc/pgbackrest/pgbackrest.conf /etc/pgbackrest/conf.d/secrets.conf" \
    | sed -e 's|^pg1-path=.*|pg1-path=/var/lib/postgresql/restore|' -e 's|^pg1-socket-path=.*|pg1-socket-path=/tmp|' \
    | grep -v '^\[global\]$' | awk 'BEGIN { print "[global]" } /^\[teabot\]$/ { s = 1 } { if (s) t = t $0 "\n"; else print } END { printf "%s", t }' \
    | docker exec -i "$NAME" sh -c 'install -d -o postgres /etc/pgbackrest /var/lib/postgresql/restore /var/log/pgbackrest /var/spool/pgbackrest && cat > /etc/pgbackrest/pgbackrest.conf && chown postgres /etc/pgbackrest/pgbackrest.conf && chmod 600 /etc/pgbackrest/pgbackrest.conf'

echo "== restore the latest backup and replay the archived WAL"
docker exec -u postgres "$NAME" pgbackrest --stanza=teabot --archive-mode=off --log-level-console=warn restore
# Ubuntu keeps postgresql.conf and pg_hba.conf outside the data directory, so the backup does not hold them.
docker exec -u postgres "$NAME" sh -c 'cd /var/lib/postgresql/restore && : > postgresql.conf && echo "local all all trust" > pg_hba.conf'
docker exec -u postgres "$NAME" pg_ctl -D /var/lib/postgresql/restore -w -t 120 -l /tmp/restore.log \
    -o "-c listen_addresses='' -c unix_socket_directories=/tmp -c archive_mode=off" start >/dev/null
for _ in $(seq 60); do
    [ "$(docker exec -u postgres "$NAME" psql -h /tmp -tAc 'SELECT pg_is_in_recovery()' 2>/dev/null)" = f ] && break
    sleep 1
done

echo "== the restored cluster"
restored=$(docker exec -u postgres "$NAME" psql -h /tmp -d teabot -tAc "$COMPARE")
restored_marker=$(docker exec -u postgres "$NAME" psql -h /tmp -d postgres -tAc "SELECT max(at) FROM restore_drill")
echo "$restored"
echo "newest marker restored: $restored_marker"
if [ "$restored" = "$host_state" ] && [ "$restored_marker" = "$marker" ]; then
    echo "restore drill passed: the scratch cluster started, holds the host's data, and replayed WAL past the backup"
else
    echo "restore drill FAILED: the restored data differs from the host's" >&2
    docker exec "$NAME" tail -20 /tmp/restore.log >&2
    exit 1
fi
