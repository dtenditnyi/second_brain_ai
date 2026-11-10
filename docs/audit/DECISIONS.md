# Decisions taken autonomously

Each entry: context · options · chosen · why · how to roll back.

## D1. Local/test database = SQLite copy, not PostgreSQL
- Context: production settings point to PostgreSQL in Docker (`DB_HOST=db`). Docker daemon is not running, `psycopg2` is not installed in the venv; rule "work only with a copy of the DB".
- Options: (a) start Docker + pg_dump the volume into a second Postgres DB; (b) SQLite copy of the legacy `db.sqlite3` + separate settings module; (c) change `settings.py` to read engine from env.
- Chosen: (b) — new files `ai_manager/settings_local.py` (copy `audit_copy_db.sqlite3`) and `ai_manager/settings_test.py` (in-memory).
- Why: zero changes to production settings, nothing installed system-wide, real data never touched. Caveat: Postgres-specific behaviour (NULL ordering, strict lengths) is not exercised — noted in TEST_PLAN.
- Rollback: delete the two settings files.

## D2. Dev dependencies installed into the project venv
- Context: rule 5 (dev deps only). Needed: pytest-django, pytest-playwright; `whitenoise` was pinned in requirements.txt but missing from venv (site could not start without it).
- Options: (a) install into existing `venv/`; (b) create a second venv (would need re-downloading torch/llama-index, GBs); (c) skip E2E.
- Chosen: (a), listed in new `requirements-dev.txt`.
- Rollback: `pip uninstall pytest-django pytest-playwright playwright`.

## D3. Browser for Playwright = installed MS Edge (`--browser-channel msedge`)
- Context: `playwright install` downloads browsers into the user profile (system-level install).
- Chosen: use the already installed Edge via channel. Rollback: n/a.

## D4. External services are always mocked in tests
- HuggingFace embedding model (downloaded at import time), Ollama, Gemini, GitHub/Git are replaced with fakes in `tests/conftest.py`. No live calls.

## D5. "Whole suite green" during phase 3
- Context: phase 3 starts with 35 deliberately failing tests (one per known defect). After each fix the full suite cannot be fully green until the last fix lands.
- Chosen: after every fix — target test(s) green AND full suite has no new failures (failing set only shrinks). Full green is required at the end of phase 3.

## D6. B-15 lazy embedding model
- Options: (a) lazy load on first chat request (`ensure_embed_model()`); (b) load in `AppConfig.ready()` (still at start); (c) env flag to skip.
- Chosen (a): smallest change, same model, same vectors. Trade-off: first chat message per process pays the load (~1–5 s). Rollback: revert commit.
