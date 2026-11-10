# Audit report — Second Brain AI

Branch `feature/audit` (from `main` @ 6a1d8ee, nothing merged into `main`). Date: 2026-11-10.
Details: `docs/SITE_MAP.md`, `docs/TEST_PLAN.md`, `docs/BUGS.md`, `docs/audit/RESPONSIVE.md`, `docs/audit/DECISIONS.md`, `docs/audit/QUESTIONS.md`, `docs/audit/LOG.md`.

## 1. What the site is
- Django 6.1, one app `core`, PostgreSQL in Docker (prod). **HTMX is not used** — the migration exists only as the unmerged branch `origin/feature/htmx-migration`; the UI is Django templates + vanilla JS `fetch()` + Tailwind v4.
- Pages: login, register, home dashboard, AI chat (RAG over your Obsidian vault: LlamaIndex + Chroma + HuggingFace embeddings; Ollama locally or Gemini in the cloud), notes viewer (wiki links + backlinks), tasks, settings, superuser "Core Matrix" admin, Django admin. 8 JSON APIs. Models: UserSettings (encrypted GitHub token), Task, ChatMessage.

## 2. Tests (none existed before)
- **278 tests** (pytest + pytest-django + pytest-playwright in installed MS Edge): unit/integration for models, auth, every page, every API, admin, RAG engine (real LlamaIndex + Chroma in a temp folder, fake LLMs), git sync; 31 E2E user flows/error/XSS cases; 74 responsive tests (11 page states × 5 widths).
- All external services are mocked (HuggingFace, Ollama, Gemini, GitHub). No real data is touched: tests use in-memory SQLite and temp folders.
- Quality checked by an independent agent using mutation testing: round 1 caught 6/9 mutations (missing tests were added), round 2 caught 5/5.
- Final run: see `docs/audit/test-run-final.txt`.

## 3. What was found and fixed (25 bugs, 15 responsive issues)
Most important:
- **Privacy (B-10):** the LLM was process-global, so a "Strictly Local" user could be answered by **another user's Gemini**, which means their notes were sent to the cloud. Each user now gets their own LLM.
- **Security:** all JSON APIs, including admin delete, had CSRF disabled (B-01). This is now enforced, and the JS sends the token. HTML/JS injection through AI replies, note names, backlinks and wiki links has been escaped (B-09, B-20, B-25).
- **Site-wide:** loading the embedding model at import made every start slow and needed network access (B-15). It is now loaded lazily, and `manage.py check` dropped from 29 s to 8 s. A missing settings row crashed every page (B-07).
- **Functional:** bad input caused 500s in the task, settings and admin APIs (B-02/03/04/17/22/24). An empty display name made login impossible (B-03). The chat greeting was never shown (B-05). Login ignored `?next=` (B-12, plus regression B-23 found by the reviewer and fixed). The cache reset wiped every user's cache (B-08). JS swallowed server errors (B-18). Stray debug text appeared in the admin page (B-16). base.html was malformed (B-19).
- **Responsive / visual:**
  - **The chat was unusable on phones and tablets.** Its window was 2 px tall (R1).
  - **Tailwind v4 had silently dropped all `bg-opacity-*` classes.** Badges, the active menu item and the selected note were solid colour with unreadable text, on every device (R2).
  - The notes text column was about 80 px wide at 1024 px (R3).
  - The admin page had no mobile layout, and its tables were clipped (R4).
  - The login and register pages scrolled sideways (R5). The password hints were black on black (R6).
  - Tap targets were smaller than 44 px (R7).
  - A modal-under-header regression from R1 was found by the verifier and fixed (R12).
  - After the fixes, 0 of 55 page × width states overflow, down from 8. Desktop layout is unchanged apart from the intended colour fix.

## 4. Not solved / left for you
- **B-14 (OPEN):** an encrypted GitHub token longer than about 140 characters would exceed `max_length=255` on Postgres. Current GitHub tokens fit. The fix needs a schema migration (`max_length=500`), so it is your decision.
- Responsive leftovers:
  - Core Matrix tables scroll sideways on small screens, with no "scroll" hint.
  - Native checkboxes are 24 px.
  - The mobile menu has no backdrop.
- Kept as-is on purpose (questions below): the PAT is shown in the settings HTML, the PAT is stored in plain text in `.git/config`, and DEBUG is hard-coded on.

## 5. Questions for you (full list: QUESTIONS.md)
1. Should DEBUG stay `True` in production? It is hard-coded; the env var is ignored.
2. Should chat have conversation memory? It currently has none, because a new engine is built for each message.
3. Should the "Generate Status Report" prompt and answer be saved in the chat history?
4. Should "Back to Dashboard" in Core Matrix go to `/notes/`?
5. Is `app_config.json` unused legacy?
6. Should changing the display name also rename your login? Empty and taken names are now rejected.
7. Should the PAT be echoed into the settings page HTML?
8. The settings label says Gemini 2.5 Flash, but the code uses `gemini-3.6-flash`. Which is right?
9. The default `OLLAMA_HOST` is a LAN IP.
10. There is no UI to set a task to "In Progress".
11. A superuser can demote or delete themselves.
12. **Chat searches only the first 10 notes by default.**
13. The PAT is stored in plain text in `.git/config`.
14. When sync fails on first use, the chat answers "Empty Response".

## 6. How to run and check
From `ai_manager/` (Windows venv in `../venv`):
```
cp db.sqlite3 audit_copy_db.sqlite3            # once; local runs use this COPY
../venv/Scripts/python.exe manage.py migrate --settings=ai_manager.settings_local
../venv/Scripts/python.exe manage.py runserver --settings=ai_manager.settings_local
../venv/Scripts/python.exe -m pytest            # all 278 tests (needs MS Edge installed)
../venv/Scripts/python.exe -m pytest -m "not e2e and not responsive"   # fast part, ~5 s
```
Dev dependencies are in `requirements-dev.txt` (pytest-django, pytest-playwright). Production settings and docker-compose are unchanged. After editing templates, rebuild the CSS with `npm run build`, and use the Tailwind v4 syntax `bg-x/20`.

## 7. Safety
- The production DB (Postgres volume) was never touched; Docker was not even running. `ai_manager/db.sqlite3` is byte-identical (sha256 5ea89448…). Work ran on `audit_copy_db.sqlite3` and on in-memory test DBs.
- `.env` was never read or committed. Only key names were listed, once, to confirm that the settings exist.
- `main` is unchanged. All work is in `feature/audit`, which is pushed to origin. No force pushes.
- One leftover: a locked, empty git worktree that the agent tooling created at `.claude/worktrees/agent-a75bfa6f39eb5319d` (branch `worktree-agent-a75bfa6f39eb5319d` at the `main` commit). It is harmless. Remove it with `git worktree remove --force .claude/worktrees/agent-a75bfa6f39eb5319d && git branch -D worktree-agent-a75bfa6f39eb5319d`.

## 8. Commits (feature/audit, oldest → newest)
b31dff8 phase-0 setup · 3a7faec site map + questions · 6992209 site map corrections · 1f27a36 unit/integration tests · 0899869 e2e + test plan + baseline · d2d433d B-15 · bebe9db B-07 · 8a0d2b9 B-10/B-08 · e61c88f B-02 · 04f1c45 tests from mutation review · f26e5e8 B-04 · bd761e3 B-03 · e528431 B-11/B-17/B-22/B-16 · 8ec5812 B-12/B-05/B-20 · cd993b9 B-01/B-19 · ae5d8c8 B-09/B-18 · 788b4e4 BUGS docs · 2fc5f6c B-23/B-24/B-25 · f0bf76c docs · faf211a B-24 round 2 + screenshot tooling · fc09c1f responsive R1–R11 · 8183112 docs · 9fb9437 responsive R12–R15 · (final docs commit)
