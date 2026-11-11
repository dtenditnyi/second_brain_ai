#!/usr/bin/env bash
# Container entrypoint (Round 3 / G-B1).
#   web        wait for Postgres → migrate → collectstatic → gunicorn
#   scheduler  wait for Postgres → run "manage.py <args>" every TASKS_SYNC_INTERVAL seconds
#   anything else is executed as is (e.g. "python manage.py createsuperuser")
set -euo pipefail

role="${1:-web}"

wait_for_db() {
    local tries="${DB_WAIT_SECONDS:-120}"
    echo "[entrypoint] waiting for PostgreSQL at ${DB_HOST:-db}:${DB_PORT:-5432} ..."
    for _ in $(seq 1 "$tries"); do
        if python - <<'PY' 2>/dev/null
import os, sys
import psycopg2
try:
    psycopg2.connect(host=os.environ.get("DB_HOST", "db"), port=os.environ.get("DB_PORT", "5432"),
                     user=os.environ.get("POSTGRES_USER", "myuser"), password=os.environ.get("POSTGRES_PASSWORD", ""),
                     dbname=os.environ.get("POSTGRES_DB", "second_brain"), connect_timeout=3).close()
except Exception:
    sys.exit(1)
PY
        then
            echo "[entrypoint] database is ready"
            return 0
        fi
        sleep 1
    done
    echo "[entrypoint] database not reachable after ${tries}s" >&2
    exit 1
}

case "$role" in
    web)
        wait_for_db
        python manage.py migrate --noinput
        python manage.py collectstatic --noinput
        exec gunicorn ai_manager.wsgi:application \
            --bind 0.0.0.0:8000 \
            --workers "${GUNICORN_WORKERS:-2}" \
            --timeout "${GUNICORN_TIMEOUT:-300}" \
            --access-logfile - --error-logfile -
        ;;
    scheduler)
        shift
        wait_for_db
        interval="${TASKS_SYNC_INTERVAL:-60}"
        echo "[entrypoint] scheduler: manage.py $* every ${interval}s"
        while true; do
            python manage.py "$@" || echo "[entrypoint] scheduled command failed (will retry)" >&2
            sleep "$interval"
        done
        ;;
    *)
        exec "$@"
        ;;
esac
