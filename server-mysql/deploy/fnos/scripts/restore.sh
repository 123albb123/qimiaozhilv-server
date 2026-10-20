#!/bin/sh
# Explicit replacement is required even when this script is called manually.
set -eu
umask 077
test "$#" = 2 && test "$2" = --confirm-data-replacement || { echo 'Usage: restore.sh /vol1/1000/docker/qimiao/backups/qimiao-UTC.sql.gz --confirm-data-replacement' >&2; exit 2; }
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/common.sh"
backup=$1
case "$backup" in "$root"/backups/qimiao-20*.sql.gz) ;; *) echo 'Backup must belong to this deployment' >&2; exit 2;; esac
test -f "$backup" && test ! -L "$backup"
test "$(CDPATH= cd -- "$(dirname -- "$backup")" && pwd -P)" = "$root/backups" || { echo 'Backup directory must be the verified project backup directory' >&2; exit 2; }
basename "$backup" | grep -Eq '^qimiao-[0-9]{8}T[0-9]{6}Z\.sql\.gz$' || { echo 'Invalid project backup filename' >&2; exit 2; }
stem=${backup%.sql.gz}
test -f "$stem.sha256"
(cd "$root/backups" && sha256sum -c "$(basename "$stem.sha256")")
gzip -t "$backup"
sh "$script_dir/backup.sh"
compose stop gm-web gm-api game
raw=$(mktemp "$root/backups/restore-XXXXXX")
trap 'rm -f "$raw"' EXIT HUP INT TERM
gzip -dc "$backup" > "$raw"
if ! compose exec -T mysql sh -ec 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot' < "$raw"; then
  echo 'Database restore failed; game and GM remain stopped. Preserve logs and restore the pre-restore backup.' >&2
  exit 1
fi
# This Redis belongs exclusively to this Compose project. Old login/session
# markers and pending commands cannot safely be replayed into an older DB.
compose exec -T redis redis-cli FLUSHDB >/dev/null
compose run --rm --no-deps init
compose up -d --no-build --wait game gm-api gm-web
printf 'Database restored and project health checks passed: %s\n' "$backup"
