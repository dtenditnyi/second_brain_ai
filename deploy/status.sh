#!/usr/bin/env bash
# One-screen health report: containers, /healthz/, disk, recent errors, last backup,
# last task sync (sync_tasks). Read-only.
set -euo pipefail

# shellcheck source=deploy/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

step "containers (docker compose ps)"
compose ps

step "healthcheck"
if healthz; then ok "/healthz/ answers"; else warn "/healthz/ does not answer"; fi

step "disk"
df -h "$REPO_DIR" | sed 's/^/  /'
docker_cmd system df 2>/dev/null | sed 's/^/  /' || true

step "recent errors (last 24 h)"
errors="$(compose logs --since 24h web scheduler 2>/dev/null | grep -iE 'error|traceback|exception' | tail -n 10 || true)"
if [ -n "$errors" ]; then echo "$errors" | sed 's/^/  /'; else ok "no errors in the last 24 h"; fi

step "backups"
if [ -f "$BACKUP_DIR/.last_backup" ]; then
    ok "last backup: $(cat "$BACKUP_DIR/.last_backup")"
    find "$BACKUP_DIR" -maxdepth 1 -name 'db-*.sql.gz' -type f -printf '  %TY-%Tm-%Td %TH:%TM  %p\n' | sort -r | head -n 3
else
    warn "no backup yet in $BACKUP_DIR (deploy/backup.sh)"
fi
systemctl list-timers secondbrain-backup.timer --no-pager 2>/dev/null | sed 's/^/  /' || true

step "tasks sync (sync_tasks)"
compose exec -T web python manage.py shell -c "
from core.models import UserSettings
rows = UserSettings.objects.exclude(github_repo_url='')
for s in rows:
    print(f'  {s.user.username}: last sync {s.tasks_last_sync or \"never\"}' + (f' — {s.tasks_sync_error[:120]}' if s.tasks_sync_error else ''))
if not rows:
    print('  no user has a vault connected')
" || warn "could not query the task sync state"
compose logs --tail 3 scheduler 2>/dev/null | sed 's/^/  /' || true
