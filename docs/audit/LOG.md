# Audit log

Format: `[YYYY-MM-DD HH:MM] Phase N · action · result · next step`

[2026-11-10 15:40] Phase 0 · Read repo layout, git log, settings, all Python views/models/rag/git_sync, all templates and JS (~2.7k lines) · Stack confirmed: Django 6.1 + PostgreSQL (docker-compose service `db`); Tailwind v4 CLI; vanilla JS (fetch + JSON APIs). **No HTMX** in the code on `main` (only a remote branch `origin/feature/htmx-migration` exists). Docker daemon is not running; the venv lacks `whitenoise` and `psycopg2` from requirements.txt · next: branch + DB copy
[2026-11-10 15:46] Phase 0 · Created branch `feature/audit` from `main` (6a1d8ee). Copied `ai_manager/db.sqlite3` → `ai_manager/audit_copy_db.sqlite3` (sha256 5ea89448… identical; git-ignored by `*.sqlite3`). The working PostgreSQL DB lives in a Docker volume and was not touched (Docker not even running) · next: deps
[2026-11-10 15:46] Phase 0 · Installed dev deps into project venv: whitenoise==6.9.0 (already pinned in requirements.txt, was missing in venv), pytest-django 4.14.0, pytest-playwright 0.10.0 (playwright 1.65.0). No browser download: Playwright uses the installed MS Edge (`channel=msedge`) · next: settings
[2026-11-10 15:47] Phase 0 · Added `ai_manager/settings_local.py` (SQLite copy, logs → git-ignored local_*.log) and `ai_manager/settings_test.py` (in-memory SQLite, null logging). `manage.py check` → no issues, but takes ~29 s because `core/rag_engine.py` downloads/loads the HuggingFace embedding model at import time (finding → BUGS) · next: migrate copy
[2026-11-10 15:47] Phase 0 · `migrate` on the copy applied missing `core.0006_usersettings_ai_strategy` (copy only) · next: run server
[2026-11-10 15:48] Phase 0 · `runserver --settings=ai_manager.settings_local` on :8765: /login/ 200, /register/ 200, all private pages 302 → /login/?next=…, /admin/ 302, static css 200. Server stopped. No pre-existing tests in the repo (0 test files) · next: CLAUDE.md, pytest config, docs
