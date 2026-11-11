#!/usr/bin/env bash
# Move the production data from the old Windows PC (Postgres in Docker Desktop) to the server.
#
#   On the OLD PC (Git Bash):   deploy/migrate-from-old-pc.sh --dump
#       → secondbrain-old-<date>.sql.gz  (read-only pg_dump; the old database is not changed)
#   Copy the file to the server, e.g.:  scp secondbrain-old-*.sql.gz user@server:~/second_brain_ai/backups/
#   On the SERVER:              deploy/migrate-from-old-pc.sh --restore backups/secondbrain-old-<date>.sql.gz
#       → deploy/restore.sh + instructions for export_tasks_to_note
set -euo pipefail

# shellcheck source=deploy/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

mode="${1:-}"
case "$mode" in
    --dump)
        container="${OLD_DB_CONTAINER:-second_brain_db}"
        target="secondbrain-old-$(date +%Y-%m-%d_%H-%M-%S).sql.gz"
        step "dump from the old container '$container' (read-only)"
        docker inspect "$container" >/dev/null 2>&1 \
            || fail "container '$container' not found — set OLD_DB_CONTAINER (docker ps --format '{{.Names}}')"
        docker exec "$container" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner' \
            | gzip -9 > "$target"
        [ -s "$target" ] || fail "empty dump"
        ok "$target ($(du -h "$target" | cut -f1)) — copy it to the server's backups/ folder"
        ;;
    --restore)
        dump="${2:-}"
        [ -n "$dump" ] || fail "usage: deploy/migrate-from-old-pc.sh --restore <file.sql.gz>"
        "$DEPLOY_DIR/restore.sh" "$dump"
        step "next: move the old tasks into the Obsidian tasks note"
        ok "1) preview:  docker compose exec web python manage.py export_tasks_to_note --user <name> --dry-run"
        ok "2) export:   docker compose exec web python manage.py export_tasks_to_note --user <name>"
        ok "   (needs the vault repository + a PAT with Contents: Read and write in Settings)"
        ;;
    *)
        sed -n '2,9p' "$0"
        exit 2
        ;;
esac
