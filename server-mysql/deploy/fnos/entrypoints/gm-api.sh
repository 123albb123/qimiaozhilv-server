#!/bin/sh
set -eu
# Preserve existing administrator password, status, permissions and sessions.
/usr/local/bin/gm-admin -username "${GM_ADMIN_USERNAME:-admin}" -if-missing
unset GM_ADMIN_PASSWORD
exec /gm-api "$@"
