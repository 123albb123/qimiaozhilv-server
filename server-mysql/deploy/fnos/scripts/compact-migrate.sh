#!/bin/sh
# One-time legacy -> four-container layout migration, with manifest rollback.
set -eu
umask 077
test "$#" = 1 || { echo 'Usage: compact-migrate.sh NEW_IMAGE_TAG' >&2; exit 2; }
tag=$1
case "$tag" in ''|*[!A-Za-z0-9_.-]*) echo 'Invalid image tag' >&2; exit 2;; esac
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
. "$script_dir/common.sh"
candidate="$root/compose.compact.next.yaml"
test -f "$candidate" && test ! -L "$candidate"
compose config --quiet
has_service gm-web && has_service init || { echo 'Migration requires the legacy layout' >&2; exit 2; }
for image in qimiao-game qimiao-gm-api qimiao-tools; do docker image inspect "$image:$tag" >/dev/null; done
MHQ_IMAGE_TAG="$tag" docker compose --project-directory "$root" --env-file "$root/.env" -f "$candidate" -p "$project" config --quiet
services=$(MHQ_IMAGE_TAG="$tag" docker compose --project-directory "$root" --env-file "$root/.env" -f "$candidate" -p "$project" config --services | sort)
test "$services" = "$(printf 'game\ngm-api\nmysql\nredis')" || { echo 'Expected exactly four normal services' >&2; exit 2; }
sh "$script_dir/backup.sh"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
saved="$root/backups/qimiao-layout-$stamp"
mkdir "$saved"
cp "$root/compose.yaml" "$saved/compose.yaml"
cp "$root/.env" "$saved/.env"
images=$(project_application_images)
test -n "$images"
set -- $images
docker image save -o "$saved/images.tar.partial" "$@"
tar -tf "$saved/images.tar.partial" | grep -q '^manifest.json$'
gzip -c "$saved/images.tar.partial" > "$saved/images.tar.gz"
gzip -t "$saved/images.tar.gz"
rm -f "$saved/images.tar.partial"
(cd "$saved" && sha256sum compose.yaml .env images.tar.gz > SHA256SUMS)
if test "$(id -u)" = 0; then chown -R 1000:1000 "$saved"; fi
modified=0
complete=0
rollback_on_exit() {
  result=$?
  trap - EXIT HUP INT TERM
  if test "$modified" = 1 && test "$complete" = 0; then
    cp "$saved/.env" "$root/.env"
    cp "$saved/compose.yaml" "$root/compose.yaml"
    if test "$(id -u)" = 0; then chown 1000:1000 "$root/.env" "$root/compose.yaml"; fi
    if compose up -d --no-build --wait --wait-timeout 180; then
      echo "Compact migration failed; previous layout and images restored. Snapshot: $saved" >&2
    else
      echo "Rollback needs attention; preserved layout snapshot: $saved" >&2
    fi
  fi
  exit "$result"
}
trap rollback_on_exit EXIT
trap 'exit 130' HUP INT TERM
modified=1
# Free the public GM port before the API takes ownership of that same port.
compose stop gm-web
sed "s/^MHQ_IMAGE_TAG=.*/MHQ_IMAGE_TAG=$tag/" "$root/.env" > "$root/.env.next"
chmod 600 "$root/.env.next"
mv "$root/.env.next" "$root/.env"
cp "$candidate" "$root/compose.yaml.next"
mv "$root/compose.yaml.next" "$root/compose.yaml"
compose up -d --no-build --wait --wait-timeout 180
# Only remove the two completed containers from this exact Compose project.
for service in gm-web init; do
  name="$project-$service-1"
  if docker container inspect "$name" >/dev/null 2>&1; then
    test "$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$name")" = "$project"
    test "$(docker inspect --format '{{index .Config.Labels "com.docker.compose.service"}}' "$name")" = "$service"
    test "$(docker inspect --format '{{.State.Running}}' "$name")" = false
    docker logs "$name" > "$saved/$service.log" 2>&1 || true
    docker rm "$name" >/dev/null
  fi
done
if test -L "$root/source" && test -d "$root/build/$tag/source"; then ln -sfn "build/$tag/source" "$root/source"; fi
if test "$(id -u)" = 0; then chown 1000:1000 "$root/.env" "$root/compose.yaml"; fi
complete=1
printf 'Compact migration healthy: four running services, snapshot=%s\n' "$saved"
