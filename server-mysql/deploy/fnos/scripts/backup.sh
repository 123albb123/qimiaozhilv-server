#!/bin/sh
# Run on fnOS, or inside the project Docker CLI helper with its socket mount.
set -eu
umask 077
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/common.sh"
test -f "$root/compose.yaml" && test -f "$root/.env"
mkdir -p "$root/backups"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
base="$root/backups/qimiao-$stamp"
test ! -e "$base.sql.gz"
raw="$base.sql.partial"
trap 'rm -f "$raw" "$base.sql.gz.partial" "$base-config.tar.gz.partial"' EXIT HUP INT TERM
compose exec -T mysql sh -ec 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot --single-transaction --routines --events --triggers --hex-blob --set-gtid-purged=OFF --databases mhq' > "$raw"
test -s "$raw"
tail -n 5 "$raw" | grep -q '^-- Dump completed on'
gzip -c "$raw" > "$base.sql.gz.partial"
gzip -t "$base.sql.gz.partial"
tar -czf "$base-config.tar.gz.partial" -C "$root" compose.yaml .env config
tar -tzf "$base-config.tar.gz.partial" >/dev/null
compose config --images > "$base-images.txt"
mv "$base.sql.gz.partial" "$base.sql.gz"
mv "$base-config.tar.gz.partial" "$base-config.tar.gz"
rm -f "$raw"
(cd "$root/backups" && sha256sum "qimiao-$stamp.sql.gz" "qimiao-$stamp-config.tar.gz" "qimiao-$stamp-images.txt" > "qimiao-$stamp.sha256")
chmod 600 "$base.sql.gz" "$base-config.tar.gz" "$base-images.txt" "$base.sha256"
# fnOS account 1000 owns user-manageable backup files; database files retain
# the MySQL image's own UID and are never chowned by this script.
if test "$(id -u)" = 0; then chown 1000:1000 "$base.sql.gz" "$base-config.tar.gz" "$base-images.txt" "$base.sha256"; fi
keep_days=${MHQ_BACKUP_KEEP_DAYS:-14}
case "$keep_days" in ''|*[!0-9]*) echo 'Invalid retention days' >&2; exit 2;; esac
test "$keep_days" -ge 1
# Only files produced by this script in the verified project backup directory.
find "$root/backups" -maxdepth 1 -type f -name 'qimiao-20*.sql.gz' -mtime "+$keep_days" -delete
find "$root/backups" -maxdepth 1 -type f -name 'qimiao-20*-config.tar.gz' -mtime "+$keep_days" -delete
find "$root/backups" -maxdepth 1 -type f -name 'qimiao-20*-images.txt' -mtime "+$keep_days" -delete
find "$root/backups" -maxdepth 1 -type f -name 'qimiao-20*.sha256' -mtime "+$keep_days" -delete
find "$root/backups" -maxdepth 1 -type f -name 'qimiao-images-20*.tar.gz' -mtime +30 -delete
find "$root/backups" -maxdepth 1 -type f -name 'qimiao-update-20*.env' -mtime +30 -delete
printf 'Backup verified: %s\n' "$base.sql.gz"
