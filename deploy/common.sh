#!/usr/bin/env bash
# Shared helpers for the deploy/*.sh scripts (sourced, not executed).
# shellcheck disable=SC2034  # variables are used by the sourcing scripts

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$DEPLOY_DIR/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$REPO_DIR/backups}"
LOG_ROOT="$REPO_DIR/logs/deploy"

if [ -t 1 ]; then
    C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_FAIL=$'\033[31m'; C_HEAD=$'\033[36m'; C_OFF=$'\033[0m'
else
    C_OK=""; C_WARN=""; C_FAIL=""; C_HEAD=""; C_OFF=""
fi

# Mirror everything this script prints into logs/deploy/<name>-<timestamp>.log.
log_setup() {
    mkdir -p "$LOG_ROOT"
    LOG_FILE="$LOG_ROOT/$1-$(date +%Y-%m-%d_%H-%M-%S).log"
    exec > >(tee -a "$LOG_FILE") 2>&1
    echo "log: $LOG_FILE"
}

step() { printf '\n%s== %s ==%s\n' "$C_HEAD" "$1" "$C_OFF"; }
ok()   { printf '  %s[ OK ]%s %s\n' "$C_OK" "$C_OFF" "$1"; }
warn() { printf '  %s[WARN]%s %s\n' "$C_WARN" "$C_OFF" "$1"; }
fail() { printf '  %s[FAIL]%s %s\n' "$C_FAIL" "$C_OFF" "$1" >&2; exit 1; }

# docker without sudo when the user is already in the docker group.
docker_cmd() {
    if docker info >/dev/null 2>&1; then docker "$@"; else sudo docker "$@"; fi
}

compose() {
    (cd "$REPO_DIR" && docker_cmd compose "$@")
}

# Value of NAME in .env WITHOUT printing it (used only for emptiness/default checks).
env_value() {
    local name="$1"
    [ -f "$REPO_DIR/.env" ] || return 0
    grep -E "^${name}=" "$REPO_DIR/.env" | tail -n 1 | cut -d= -f2- | tr -d '\r'
}

# Checks that the required variables exist and are not placeholders. Values are never shown.
check_env() {
    [ -f "$REPO_DIR/.env" ] || fail ".env not found — copy .env.example to .env and fill it in (docs/DEPLOY.md)"
    local missing=0 name value
    for name in SECRET_KEY POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD; do
        value="$(env_value "$name")"
        case "$value" in
            ""|change-me|change-me-to-a-long-random-string|default-insecure-key-for-dev|mypassword)
                warn "$name is missing or still the example value"; missing=1 ;;
            *) ok "$name is set" ;;
        esac
    done
    value="$(env_value SECRET_KEY)"
    if [ -n "$value" ] && [ "${#value}" -lt 40 ]; then
        warn "SECRET_KEY is shorter than 40 characters"; missing=1
    fi
    for name in CLOUDFLARE_TUNNEL_TOKEN GEMINI_API_KEY; do
        value="$(env_value "$name")"
        case "$value" in
            ""|your-tunnel-token|your-gemini-api-key) warn "$name is not set (optional, see docs/DEPLOY.md)" ;;
            *) ok "$name is set" ;;
        esac
    done
    [ "$missing" -eq 0 ] || fail "fill in the variables above in .env, then run the script again"
}

# Wait until the web container reports "healthy" (Docker healthcheck → /healthz/).
wait_healthy() {
    local timeout="${1:-600}" waited=0 cid status
    while [ "$waited" -lt "$timeout" ]; do
        cid="$(compose ps -q web 2>/dev/null || true)"
        if [ -n "$cid" ]; then
            status="$(docker_cmd inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo unknown)"
            if [ "$status" = "healthy" ]; then
                ok "web is healthy (/healthz/) after ${waited}s"
                return 0
            fi
        fi
        sleep 5
        waited=$((waited + 5))
    done
    return 1
}

healthz() {
    compose exec -T web python -c "import sys, urllib.request; r = urllib.request.urlopen('http://127.0.0.1:8000/healthz/', timeout=5); print(r.read().decode()); sys.exit(0 if r.status == 200 else 1)"
}
