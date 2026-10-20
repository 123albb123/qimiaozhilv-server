#!/bin/sh
# Build/import the current layout's application images and tools first.
set -eu
umask 077
test "$#" = 1 || { echo 'Usage: update.sh NEW_IMAGE_TAG' >&2; exit 2; }
tag=$1
case "$tag" in ''|*[!A-Za-z0-9_.-]*) echo 'Invalid image tag' >&2; exit 2;; esac
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/common.sh"
compose config --quiet
images=$(project_application_images)
test -n "$images"
for image in $images; do docker image inspect "${image%:*}:$tag" >/dev/null; done
sh "$script_dir/backup.sh"
previous=$(sed -n 's/^MHQ_IMAGE_TAG=//p' "$root/.env")
test -n "$previous"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
saved="$root/backups/qimiao-update-$stamp.env"
cp "$root/.env" "$saved"
# Preserve the exact old images for offline rollback; unrelated images are
# never touched. Do this before replacing the deployment's version tag.
raw_images="$root/backups/qimiao-images-$stamp.tar.partial"
trap 'rm -f "$raw_images"' EXIT HUP INT TERM
set -- $images
docker image save -o "$raw_images" "$@"
tar -tf "$raw_images" | grep -q '^manifest.json$'
gzip -c "$raw_images" > "$root/backups/qimiao-images-$stamp.tar.gz"
gzip -t "$root/backups/qimiao-images-$stamp.tar.gz"
rm -f "$raw_images"
if test "$(id -u)" = 0; then chown 1000:1000 "$saved" "$root/backups/qimiao-images-$stamp.tar.gz"; fi
sed "s/^MHQ_IMAGE_TAG=.*/MHQ_IMAGE_TAG=$tag/" "$root/.env" > "$root/.env.next"
chmod 600 "$root/.env.next"
mv "$root/.env.next" "$root/.env"
if compose config --quiet && compose up -d --no-build --wait --wait-timeout 180; then
  # Keep future source builds aligned with the installed image version.
  if test -L "$root/source" && test -d "$root/build/$tag/source"; then
    ln -sfn "build/$tag/source" "$root/source"
  fi
  if test "$(id -u)" = 0; then chown 1000:1000 "$root/.env" "$saved" "$root/backups/qimiao-images-$stamp.tar.gz"; fi
  printf 'Update healthy: %s -> %s\n' "$previous" "$tag"
else
  cp "$saved" "$root/.env"
  if test "$(id -u)" = 0; then chown 1000:1000 "$root/.env"; fi
  compose up -d --no-build --wait --wait-timeout 180
  echo "Update failed; application images rolled back to $previous. Database was not automatically rolled back; use the verified backup if a migration is incompatible." >&2
  exit 1
fi
