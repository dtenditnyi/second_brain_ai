#!/usr/bin/env bash
# Daily backup (systemd timer 03:30, docs/DEPLOY.md).
#   deploy/backup.sh               compressed pg_dump of the database
#   deploy/backup.sh --with-files  also chroma_db + obsidian_data volumes (tar.gz)
# Keeps the last KEEP (default 14) backups of each kind in BACKUP_DIR (default ./backups).
set -euo pipefail

# shellcheck source=deploy/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
log_setup backup

KEEP="${KEEP:-14}"
WITH_FILES=0
for arg in "$@"; do
    case "$arg" in
        --with-files) WITH_FILES=1 ;;
        -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
        *) fail "unknown option: $arg" ;;
    esac
done

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
stamp="$(date +%Y-%m-%d_%H-%M-%S)"

step "database (pg_dump)"
target="$BACKUP_DIR/db-$stamp.sql.gz"
# The dump runs inside the db container with its own credentials; output is gzip-compressed.
compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' \
    | gzip -9 > "$target.part"
mv "$target.part" "$target"
[ -s "$target" ] || fail "empty dump: $target"
ok "$target ($(du -h "$target" | cut -f1))"

if [ "$WITH_FILES" -eq 1 ]; then
    step "files (chroma_db, obsidian_data)"
    project="$(basename "$REPO_DIR" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')"
    for volume in chroma_db obsidian_data; do
        archive="$BACKUP_DIR/$volume-$stamp.tar.gz"
        docker_cmd run --rm -v "${COMPOSE_PROJECT_NAME:-$project}_${volume}:/data:ro" -v "$BACKUP_DIR:/backup" \
            alpine:3.20 tar czf "/backup/$(basename "$archive")" -C /data .
        ok "$archive"
    done
fi

step "rotation (keep $KEEP)"
for prefix in db chroma_db obsidian_data; do
    # newest first; everything after the first KEEP files is removed
    find "$BACKUP_DIR" -maxdepth 1 -name "${prefix}-*" -type f -printf '%T@ %p\n' \
        | sort -rn | tail -n "+$((KEEP + 1))" | cut -d' ' -f2- \
        | while read -r old; do rm -f -- "$old"; echo "  removed $old"; done
done
date -Iseconds > "$BACKUP_DIR/.last_backup"
ok "backup complete"
