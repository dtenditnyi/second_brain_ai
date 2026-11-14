#!/usr/bin/env bash
# Update Second Brain to the latest commit of the current branch (docs/DEPLOY.md).
#   git pull → backup → rebuild → restart (migrations run in the entrypoint) → /healthz/
# If the new version does not become healthy, it rolls back to the previous commit and
# image. Database migrations are not reverted automatically: restore the backup made
# at the start (deploy/restore.sh) if a migration broke something.
# -E: the ERR trap must also fire inside shell functions such as compose (B-46)
set -Eeuo pipefail

# shellcheck source=deploy/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
log_setup update
cd "$REPO_DIR"

# The commit that is really running is remembered in .deployed_commit, so a failed
# build cannot make the next run think it is "already up to date" (B-39).
state_file="$REPO_DIR/.deployed_commit"

step "1/5 git pull"
previous="$(cat "$state_file" 2>/dev/null || git rev-parse HEAD)"
git pull --ff-only
current="$(git rev-parse HEAD)"
if [ "$previous" = "$current" ] && [ "${1:-}" != "--force" ]; then
    ok "already up to date ($(git rev-parse --short HEAD)); use --force to rebuild anyway"
    exit 0
fi
# Any failure from here on (build error, …) puts the checkout back to what runs.
trap 'warn "update failed — checkout reset to $(git rev-parse --short "$previous")"; git reset --hard "$previous" >/dev/null' ERR
ok "$(git rev-parse --short "$previous") → $(git rev-parse --short "$current")"

step "2/5 backup before the update"
"$DEPLOY_DIR/backup.sh"

step "3/5 build the new image (old one kept for rollback)"
if docker_cmd image inspect secondbrain-web:latest >/dev/null 2>&1; then
    docker_cmd tag secondbrain-web:latest secondbrain-web:rollback
fi
compose build
ok "built"

step "4/5 restart"
compose up -d --remove-orphans
ok "restarted"

step "5/5 healthcheck"
if wait_healthy 600 && healthz; then
    trap - ERR
    git rev-parse HEAD > "$state_file"
    ok "update finished: $(git log -1 --format='%h %s')"
    exit 0
fi
trap - ERR

warn "new version is not healthy — starting rollback to $(git rev-parse --short "$previous")"
compose logs --tail 80 web || true
git reset --hard "$previous"
if docker_cmd image inspect secondbrain-web:rollback >/dev/null 2>&1; then
    docker_cmd tag secondbrain-web:rollback secondbrain-web:latest
    compose up -d --no-build --remove-orphans
else
    compose up -d --build --remove-orphans
fi
if wait_healthy 600; then
    warn "rollback done: running $(git rev-parse --short HEAD) again. If a migration failed, restore the backup: deploy/restore.sh"
else
    fail "rollback did not become healthy either — see docs/DEPLOY.md («Сайт не открывается»)"
fi
exit 1
