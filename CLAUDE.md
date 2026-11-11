# Second Brain AI — notes for Claude

Django 6.1 app (single app `core`) in `ai_manager/`. Production DB: PostgreSQL (docker-compose `db`).
Frontend: Django templates + vanilla JS (`ai_manager/static/js/*.js`) + Tailwind v4 CLI (`static/css/input.css` → `styles.css`).
AI: `core/rag_engine.py` (LlamaIndex + Chroma + HuggingFace embeddings; Ollama local / Gemini cloud). Git vault sync: `core/git_sync.py`.

## Launcher (repo root) — main way to start
- `start.bat` (→ `start.ps1`): env checks → DB copy (only if missing) → `check` + `migrate` (settings_local)
  → `npm run build` → fast tests → `runserver` + browser. Switches: `-Install`, `-FullTests`, `-SkipTests`,
  `-Force` (start even if tests fail), `-Port N`, `-Watch`, `-Tunnel`, `-Docker` (prod compose!), `-NoBrowser`, `-NoServer`.
- Logs: `logs/runs/run_*.log` (last 30 kept, git-ignored) + `logs/runs/history.csv`. Never reads `.env`.
- AI env vars (see `.env.example`): `GEMINI_MODEL_DEFAULT/SMART`, `GEMINI_FALLBACK_MODELS`, `OLLAMA_HOST`,
  `CHAT_HISTORY_MESSAGES`, `PROMPT_TOKEN_BUDGET_*`; labels/limits in `core/ai_models.py`.
  `scripts/list_gemini_models.py` lists the key's models (owner runs it; it calls Google).

## Production / tasks (Round 3)
- Prod: `Dockerfile` (multi-stage), `docker-compose.yml` (db, web, scheduler, tunnel), `docker/entrypoint.sh`,
  scripts in `deploy/` (bash, LF via `.gitattributes`); step-by-step guide: `docs/DEPLOY.md` (Russian). `/healthz/` = probe.
  Compose check without the real `.env`: `ENV_FILE=.env.test.example docker compose --env-file .env.test.example config --quiet`.
- Tasks: one Obsidian note is the source of truth (`docs/TASKS_FORMAT.md`); `core/tasks_md.py` (pure parser),
  `core/vault_writer.py` (THE only way to write to a vault: lock → pull → op → commit → push, retry),
  `core/tasks_service.py` (cache + outbox); `manage.py sync_tasks`, `export_tasks_to_note`.
  Tests use local bare repos (`tests/vault_helpers.py`); conftest blocks real git unless a test patches `Repo`.

## Round 4 (editor, agent, API)
- Notes editor: `core/notes_service.py` (save with SHA conflicts, offline outbox, rename with link update, per-note re-index),
  `core/views/notes_api.py`, `static/js/note_editor.js` + bundled CodeMirror `static/vendor/sb-editor.js`.
- AI: `core/ai_providers.py` (Gemini chain / Ollama / Claude, one `chat()`), `core/agent.py` (tools → overlay →
  `AgentBatch`, apply/reject/revert; never writes without confirmation), chat UI `static/js/agent_chat.js`.
- REST API: `core/api_v1.py` (+ `url_normalize.py`, `frontmatter.py`), docs `docs/API.md`; the Link2Note contract
  `docs/link2note/API_CONTRACT.md` + `contract/*.json` is checked by `tests/test_api_contract.py`. Allowed tags: ONE setting `ALLOWED_TAGS`.
- Tests: `settings_test` adds `tests/serial_middleware.py` (live_server + in-memory SQLite → one request at a time).

## Commands (run from `ai_manager/`, Windows venv at `../venv`)
- Local server on a SQLite **copy** of the DB (never the prod DB). On a fresh checkout create the copy first
  (only if missing): `cp db.sqlite3 audit_copy_db.sqlite3` (path override: env `AUDIT_SQLITE_PATH`). Default port 8000.
  `.env` is optional for local start (SECRET_KEY falls back to a dev key; AI needs GEMINI_API_KEY/OLLAMA_HOST).
  `../venv/Scripts/python.exe manage.py migrate --settings=ai_manager.settings_local`
  `../venv/Scripts/python.exe manage.py runserver --settings=ai_manager.settings_local`
  (first import of `core.rag_engine` loads the HF embedding model — slow, needs network once)
- Tailwind (in `ai_manager/`, where package.json is; styles.css is committed so not needed to start): `npm run build` (one-off) / `npm run dev` (watch)
- Tests (all, incl. Playwright E2E via installed MS Edge): `../venv/Scripts/python.exe -m pytest`
  - only unit/integration: `-m "not e2e and not responsive"`; responsive only: `-m responsive`
  - screenshots (11 sizes, `responsive_helpers.SHOT_SIZES`): `SCREENSHOT_DIR=../docs/audit/responsive/round2/after ../venv/Scripts/python.exe -m pytest tests/e2e/test_screenshots.py`
  - design system: tokens + components (`.btn`, `.field`, `.badge`, `.modal-overlay`, `.empty-state`, …) in `static/css/input.css`; use `text-fg/text-soft/text-muted`, `bg-accent/10`, not `opacity-*` on text
  - after editing templates/CSS: `npx @tailwindcss/cli -i ./static/css/input.css -o ./static/css/styles.css --minify` (Tailwind v4: use `bg-x/20`, not `bg-opacity-20`)
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
