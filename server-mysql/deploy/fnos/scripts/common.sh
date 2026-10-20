#!/bin/sh
# Production and an explicitly opted-in, unpublished maintenance-test project.
root=${MHQ_DEPLOY_DIR:-/vol1/1000/docker/qimiao}
case "$root" in
  /vol1/1000/docker/qimiao) project=qimiao ;;
  /vol1/1000/docker/qimiao/isolated/maintenance-test)
    test "${MHQ_MAINTENANCE_TEST:-}" = 1 || { echo 'Explicit isolated maintenance-test opt-in required' >&2; exit 2; }
    project=qimiao-maintenance-test ;;
  *) echo 'Unexpected deployment directory' >&2; exit 2 ;;
esac
test -d "$root" && test ! -L "$root"
test "$(CDPATH= cd -- "$root" && pwd -P)" = "$root" || { echo 'Deployment root must resolve to its verified path' >&2; exit 2; }
compose() { docker compose --project-directory "$root" --env-file "$root/.env" -f "$root/compose.yaml" -p "$project" "$@"; }
