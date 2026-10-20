#!/bin/sh
# Production and an explicitly opted-in, unpublished maintenance-test project.
root=${MHQ_DEPLOY_DIR:-/vol1/1000/docker/qimiao}
case "$root" in
  /vol1/1000/docker/qimiao) project=qimiao ;;
  /vol1/1000/docker/qimiao/isolated/maintenance-test|/vol1/1000/docker/qimiao/isolated/compact-test)
    test "${MHQ_MAINTENANCE_TEST:-}" = 1 || { echo 'Explicit isolated maintenance-test opt-in required' >&2; exit 2; }
    case "$root" in */compact-test) project=qimiao-compact-test ;; *) project=qimiao-maintenance-test ;; esac ;;
  *) echo 'Unexpected deployment directory' >&2; exit 2 ;;
esac
test -d "$root" && test ! -L "$root"
test "$(CDPATH= cd -- "$root" && pwd -P)" = "$root" || { echo 'Deployment root must resolve to its verified path' >&2; exit 2; }
compose() { docker compose --project-directory "$root" --env-file "$root/.env" -f "$root/compose.yaml" -p "$project" "$@"; }

has_service() { compose config --services | grep -qx "$1"; }

application_services() {
  if has_service gm-web; then echo 'gm-web gm-api game'; else echo 'gm-api game'; fi
}

project_application_images() {
  compose --profile '*' config --images | while IFS= read -r image; do
    case "$image" in
      qimiao-game:*|qimiao-gm-api:*|qimiao-gm-web:*|qimiao-tools:*) printf '%s\n' "$image" ;;
    esac
  done | sort -u
}
