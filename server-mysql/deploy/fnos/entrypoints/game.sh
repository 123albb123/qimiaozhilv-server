#!/bin/sh
set -eu
# The existing atomic/idempotent importer is the startup barrier. A failure
# leaves the game closed; an initialized database is never re-seeded.
/usr/local/bin/import-config -initial-only -table /bootstrap/tables -skill-logic /bootstrap/SkillLogicConfig.yaml
exec /mhqserver "$@"
