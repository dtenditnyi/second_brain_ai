# Second Brain AI — notes for Claude

Django 6.1 app (single app `core`) in `ai_manager/`. Production DB: PostgreSQL (docker-compose `db`).
Frontend: Django templates + vanilla JS (`ai_manager/static/js/*.js`) + Tailwind v4 CLI (`static/css/input.css` → `styles.css`).
AI: `core/rag_engine.py` (LlamaIndex + Chroma + HuggingFace embeddings; Ollama local / Gemini cloud). Git vault sync: `core/git_sync.py`.

## Commands (run from `ai_manager/`, Windows venv at `../venv`)
- Local server on a SQLite **copy** of the DB (never the prod DB). On a fresh checkout create the copy first
  (only if missing): `cp db.sqlite3 audit_copy_db.sqlite3` (path override: env `AUDIT_SQLITE_PATH`). Default port 8000.
  `.env` is optional for local start (SECRET_KEY falls back to a dev key; AI needs GEMINI_API_KEY/OLLAMA_HOST).
  `../venv/Scripts/python.exe manage.py migrate --settings=ai_manager.settings_local`
  `../venv/Scripts/python.exe manage.py runserver --settings=ai_manager.settings_local`
  (first import of `core.rag_engine` loads the HF embedding model — slow, needs network once)
- Tailwind (in `ai_manager/`, where package.json is; styles.css is committed so not needed to start): `npm run build` (one-off) / `npm run dev` (watch)
- Tests (all, incl. Playwright E2E via installed MS Edge): `../venv/Scripts/python.exe -m pytest`
  - only unit/integration: `-m "not e2e and not responsive"`
  - settings: `ai_manager/settings_test.py` (in-memory SQLite, logs to null)
- Docker/prod: `docker compose up` (gunicorn, Postgres, cloudflared).

## Structure
- `core/models.py` UserSettings (1:1 User, encrypted GitHub token), Task, ChatMessage
- `core/views/{auth,pages,api,admin}.py`, routes in `core/urls.py`
- `templates/` base.html + sidebar.html shell; pages extend base.html
- `tests/` pytest suite; `tests/e2e/` Playwright
- Audit docs: `docs/SITE_MAP.md`, `docs/TEST_PLAN.md`, `docs/BUGS.md`, `docs/audit/*`

## Rules
- Never read/commit `.env`; external APIs (Gemini, Ollama, GitHub, HF) are always mocked in tests.
