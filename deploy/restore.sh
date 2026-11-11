#!/usr/bin/env bash
# Restore the database from a backup made by backup.sh (or by migrate-from-old-pc.sh).
#   deploy/restore.sh backups/db-2026-11-11_03-30-00.sql.gz
# Asks for confirmation: the current database content is REPLACED.
set -euo pipefail

# shellcheck source=deploy/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
log_setup restore

dump="${1:-}"
[ -n "$dump" ] || fail "usage: deploy/restore.sh <backup.sql.gz>"
[ -f "$dump" ] || fail "file not found: $dump"
gzip -t "$dump" || fail "not a valid gzip file: $dump"

step "confirmation"
warn "This REPLACES the current database with $(basename "$dump")."
warn "A safety backup of the current state is made first."
read -r -p "  Type RESTORE to continue: " answer
[ "$answer" = "RESTORE" ] || fail "cancelled"

step "safety backup"
"$DEPLOY_DIR/backup.sh"

step "stop the application (database keeps running)"
compose stop web scheduler || true
compose up -d db
ok "web and scheduler stopped"

step "restore"
# The dump was made with --clean --if-exists, so existing tables are dropped first.
gunzip -c "$dump" | compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -q -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
ok "database restored"

step "start again"
compose up -d
if wait_healthy 600; then
    ok "restore complete"
else
    fail "web is not healthy after the restore — see deploy/status.sh"
fi
