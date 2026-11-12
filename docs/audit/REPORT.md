# Audit report — Second Brain AI

Branch `feature/audit` (from `main` @ 6a1d8ee, nothing merged into `main`). Date: 2026-11-10.
Details: `docs/SITE_MAP.md`, `docs/TEST_PLAN.md`, `docs/BUGS.md`, `docs/audit/RESPONSIVE.md`, `docs/audit/DECISIONS.md`, `docs/audit/QUESTIONS.md`, `docs/audit/LOG.md`.

## 1. What the site is
- Django 6.1, one app `core`, PostgreSQL in Docker (prod). **HTMX is not used** — the migration exists only as the unmerged branch `origin/feature/htmx-migration`; the UI is Django templates + vanilla JS `fetch()` + Tailwind v4.
- Pages: login, register, home dashboard, AI chat (RAG over your Obsidian vault: LlamaIndex + Chroma + HuggingFace embeddings; Ollama locally or Gemini in the cloud), notes viewer (wiki links + backlinks), tasks, settings, superuser "Core Matrix" admin, Django admin. 8 JSON APIs. Models: UserSettings (encrypted GitHub token), Task, ChatMessage.

## 2. Tests (none existed before)
- **279 tests collected: 278 pass + 1 skipped screenshot tool** (pytest + pytest-django + pytest-playwright in installed MS Edge): unit/integration for models, auth, every page, every API, admin, RAG engine (real LlamaIndex + Chroma in a temp folder, fake LLMs), git sync; 28 E2E user flows/error/XSS cases; 74 responsive tests (176 unit/integration + 28 E2E + 74 responsive) (11 page states × 5 widths).
- All external services are mocked (HuggingFace, Ollama, Gemini, GitHub). No real data is touched: tests use in-memory SQLite and temp folders.
- Quality checked by an independent agent using mutation testing: round 1 caught 6/9 mutations (missing tests were added), round 2 caught 5/5.
- Final run: see `docs/audit/test-run-final.txt`.

## 3. What was found and fixed (25 bugs found: 21 fixed, 1 open, 3 kept as questions; 15 responsive issues fixed)
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
- **B-14 (OPEN):** a GitHub token of 128+ characters (encrypts to > 255 chars) would exceed `max_length=255` on Postgres. Current GitHub tokens fit. The fix needs a schema migration (`max_length=500`), so it is your decision.
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
- One leftover: a locked git worktree (checked out at `main` 6a1d8ee, no changes) that the agent tooling created at `.claude/worktrees/agent-a75bfa6f39eb5319d` (branch `worktree-agent-a75bfa6f39eb5319d` at the `main` commit). It is harmless. Remove it with `git worktree remove --force .claude/worktrees/agent-a75bfa6f39eb5319d && git branch -D worktree-agent-a75bfa6f39eb5319d`.

## 8. Commits (feature/audit, oldest → newest)
b31dff8 phase-0 setup · 3a7faec site map + questions · 6992209 site map corrections · 1f27a36 unit/integration tests · 0899869 e2e + test plan + baseline · d2d433d B-15 · bebe9db B-07 · 8a0d2b9 B-10/B-08 · e61c88f B-02 · 04f1c45 tests from mutation review · f26e5e8 B-04 · bd761e3 B-03 · e528431 B-11/B-17/B-22/B-16 · 8ec5812 B-12/B-05/B-20 · cd993b9 B-01/B-19 · ae5d8c8 B-09/B-18 · 788b4e4 BUGS docs · 2fc5f6c B-23/B-24/B-25 · f0bf76c docs · faf211a B-24 round 2 + screenshot tooling · fc09c1f responsive R1–R11 · 8183112 docs · 9fb9437 responsive R12–R15 · f7ca375 final run + report · (last commit: audit remarks)

---

# Round 2

Branch `feature/audit` (continues Round 1; nothing merged into `main`). Date: 2026-11-10. Task: `docs/audit/PROMPT_ROUND2.md`.

## R2.1 What was done

**Owner answers (section 1) — all 14 implemented, plus B-14:**

| Q | Result |
|---|---|
| 1 DEBUG | `DEBUG = os.getenv('DEBUG', 'False') == 'True'`; `settings_local` forces `True`. With DEBUG off, WhiteNoise serves files after `collectstatic` and the new 404/500 pages render (tests). |
| 2 Chat memory | The last `CHAT_HISTORY_MESSAGES` (6) messages of the **same** user are sent, cut to a token budget; system notices are not fed back. |
| 3 Status report | Sent with `mode: "report"`: SMART model, no memory, **not** stored in the chat history. |
| 4 Back to Dashboard | Goes to `/`. |
| 5 app_config.json | Deleted (grep: only referenced by audit docs). |
| 6 Display name | Separate from the login (the field already existed; data migration fills empty values). Shown in the sidebar, greeting and the AI system prompt. The login changes only via Core Matrix. |
| 7 PAT in HTML | The field is always empty; "Token saved — leave empty to keep it"; empty = keep; a "Delete the saved token" checkbox. Test: the token is not in the page source. |
| 8 Model label | Labels come from `core/ai_models.py` with the same IDs the code uses (section 3). |
| 9 OLLAMA_HOST | Env only, default `http://localhost:11434`; no LAN IP anywhere (test). In `.env.example`/README. |
| 10 In Progress | To Do / In Progress / Done select on the Tasks page and on Home board cards. Unchecking "done" → To Do (D10). |
| 11 Superuser guard | Cannot remove your own superuser flag or delete your own account (backend 400 + disabled controls). Found and fixed on the way: a save without the `is_superuser` key demoted the user (B-26). |
| 12 Whole vault | Nothing is pre-checked; "Searching the whole vault" / "Selected: N notes" + Reset. |
| 13 PAT not in .git/config | The token reaches git only through per-process env (`http.extraHeader`); the origin URL is always the plain URL (also cleans old tokenised URLs, also on errors). Tested with real local repos. |
| 14 Clear sync error | "Could not sync your vault with GitHub — check the repository URL and token in Settings." / "Your vault index is empty…" instead of "Empty Response". |
| B-14 | Migration 0007: `github_token` `max_length=500`; a 200-character token round-trips (test). |

**Launcher (section 2):** `start.bat` → `start.ps1` (details in R2.3).

**Gemini models (section 3):**
- `GEMINI_MODEL_DEFAULT` = `gemini-3.5-flash-lite`, `GEMINI_MODEL_SMART` = `gemini-3.8-flash`, `GEMINI_FALLBACK_MODELS` = `gemini-3.1-flash-lite,gemma-4-31b-it`. IDs come from Google's docs, except `gemini-3.1-flash-lite`, which is **not confirmed** (D13). Run `scripts/list_gemini_models.py` (not executed by me) and adjust `.env`.
- On 429 / `RESOURCE_EXHAUSTED` / unavailable model, the next model in the chain is tried. After the whole chain fails: Auto-Hybrid → Ollama; Cloud Only → "The daily limit of the cloud models is exhausted — try again later or switch to local mode". Other errors are not masked.
- The model that answered is logged and stored per user. It is shown on Home, in Chat (under each answer) and in Settings, with no extra calls to Google.
- Gemma: prompt ≈ 8K tokens (top-k 3, history trimmed), and the system prompt is placed inside the first user message.
- The settings dropdown shows real names and daily limits, e.g. "Fast: Gemini 3.5 Flash Lite (~500/day)".

**Responsive & visual (section 4):** design system, mobile menu backdrop / Esc / scroll lock, Core Matrix as cards on phones, 44 px tap zones, safe areas, `dvh` chat with a pinned composer, 16 px inputs, AA contrast in both themes, focus ring, skip link, reduced motion, no theme flash. Checked at 11 sizes; see `docs/audit/RESPONSIVE.md` (R16–R26) and `responsive/round2/before|after/`.

## R2.2 Tests
- **592 tests collected: 591 passed, 1 skipped** (the screenshot tool, which runs only with `SCREENSHOT_DIR`). The final run used the launcher itself: `start.bat -FullTests -NoServer` → `docs/audit/test-run-round2.txt`.
  - 265 unit/integration tests (Round 1: 176).
  - 38 end-to-end tests (28).
  - 289 responsive tests (74), now at 11 sizes, plus tap zones on phones and touch tablets, 16 px inputs, chat composer, modals, Core Matrix cards, focus, reduced motion, and the contrast of rendered text in 2 themes × 3 accents.
- Tests that pinned the old behaviour (characterization of Q2, Q6, Q7, Q12 and Q14) were replaced by tests for the new behaviour.
- New tests cover:
  - Q13 with real local git repositories.
  - DEBUG off + WhiteNoise + 404/500.
  - The fallback chain: a 429 on the first model → the second model answers; the whole chain exhausted → Ollama or a clear message.
  - Gemma's inline system prompt and ≤ 8K budget, also for Russian text.
  - Per-user memory isolation; the report is not stored.
- Mutation checks:
  - Restoring the old light-theme colour fails the contrast test.
  - The final auditor removed the `finally` cleanup in git_sync and made the report get saved; the tests caught both.
- External services stay mocked (Gemini, Ollama, GitHub, HuggingFace).

## R2.3 How to run
From the repository root: **`start.bat`** (double-click works). The steps are: environment checks → local DB copy (only if missing) → `check` + `migrate` (settings_local) → `npm run build` → fast tests → server on http://127.0.0.1:8000 + browser.

| Switch | Effect |
|---|---|
| `-Install` | `pip install -r requirements.txt -r requirements-dev.txt` + `npm install` |
| `-FullTests` / `-SkipTests` | all tests incl. Playwright / no tests |
| `-Force` | start the server even if tests failed (and skip the `-Docker` confirmation) |
| `-Port N` | server port (default 8000) |
| `-Watch` / `-Tunnel` | Tailwind watch / cloudflared tunnel in separate windows |
| `-Docker` | `docker compose up --build` instead of the local mode (**production** config, asks for YES) |
| `-NoBrowser` / `-NoServer` | do not open the browser / only checks + tests |

Logs: `logs/runs/run_YYYY-MM-DD_HH-mm-ss.log` (last 30 kept) and `logs/runs/history.csv`. `.env` is never read. Verified by real runs: `-SkipTests` + server, fast tests, a failing test (the server is not started), a collection error, fast tests + server, `-FullTests -NoServer` (the final run), and log retention (37 → 30). **Not run:** `-Install`, `-Watch`, `-Tunnel`, `-Docker`.

## R2.4 New environment variables
`DEBUG` (now honoured), `OLLAMA_HOST` (default localhost), `OLLAMA_MODEL`, `GEMINI_MODEL_DEFAULT`, `GEMINI_MODEL_SMART`, `GEMINI_FALLBACK_MODELS`, `CHAT_HISTORY_MESSAGES`, `PROMPT_TOKEN_BUDGET_GEMMA` / `_GEMINI` / `_LOCAL`. All are listed in `.env.example`. New migrations: 0007 (token length), 0008 (fill display_name), 0009 (last model). They must be applied on Postgres with `migrate` when deploying.

## R2.5 What is left / for you
- Independent checks by two separate agents:
  - **Responsive verifier.** It found a light-theme contrast failure, touch targets at 1024 px, a desktop regression in the Notes explorer and a cramped landscape chat. All fixed in 49ee379 (R27–R30).
  - **Final auditor.** Overall PASS. It found that a superuser could still delete their own account using ids like "01" / 2.0, that the token budget underestimated Cyrillic, that the Ollama fallback had no re-probe, that 500/network errors did not move to the next model, and two launcher edge cases. All fixed in 1afdf64 (D19).
- Not changed (your call):
  - Core Matrix keeps its own always-dark "console" style. It is not part of the light theme, but it uses the shared touch and contrast rules.
  - From 768 px the wide admin tables still scroll sideways (scroll shadows show this).
  - `ai_manager/logs/rag_engine.log` is still tracked and contains the old LAN IP. This predates the audit.
  - In phone landscape (667×375) the chat feed is small but usable (≥ 100 px, tested).
- Check the Gemini model IDs with `scripts/list_gemini_models.py`, especially `gemini-3.1-flash-lite`.
- Production: compose already sets `DEBUG=False`, which is now honoured. `collectstatic` runs in the compose command. Apply migrations 0007–0009 on Postgres.
- Token budgets are estimates (≈ 4 characters per token); a real tokenizer is not used.
- The chat still shows AI answers as plain text (Markdown is not rendered; this is unchanged).

## R2.6 Safety
- The production DB was not touched (Docker not started). `ai_manager/db.sqlite3` is unchanged (sha256 5ea89448…). Migrations 0007–0009 were applied only to `audit_copy_db.sqlite3` and the in-memory test DBs.
- `.env` was not read or committed. The launcher only checks whether it exists. `scripts/list_gemini_models.py` was not executed.
- Gemini, Ollama, GitHub and HuggingFace are mocked in all tests. Two web searches on ai.google.dev were made to look up model IDs; no project data was sent.
- `main` is unchanged. The leftover worktree `.claude/worktrees/agent-a75bfa6f39eb5319d` and the branch `worktree-agent-a75bfa6f39eb5319d` were removed (clean, at the `main` commit).

## R2.7 Commits (Round 2)
758145b Q13 PAT not in .git/config · 2cb8e41 Q5 remove app_config.json · 5a76f6a Q11 + B-26 Core Matrix self-protection · c52427f Q1/Q8/Q9 DEBUG, 404/500, AI config · 4a751f6 Q2/Q3/Q6/Q7/Q12/Q14 + B-14 + Gemini chain · e3dcb36 design system + Round 2 UI · 80bf980 launcher, .env.example, README/CLAUDE.md · 8bcb359 retry sync after empty index · 49ee379 verifier findings · d0c3234 docs + screenshots · 1afdf64 final-audit findings · (last commit: final docs)

---

# Round 3 — Markdown in chat, Core Matrix polish, tasks in an Obsidian note, home-server production

Branch `feature/round3` (from `main` after merging `feature/audit`, 6ed60c4). Task: `docs/audit/PROMPT_ROUNDS_3-5.md` → Round 3. Goals and criteria: `docs/audit/round3/GOALS.md`.

## R3.1 What was done
- **A1 Markdown in AI answers** (chat + status report): marked + DOMPurify + highlight.js, served locally from `static/vendor/`. Supports headings, lists, tables, code with highlighting and a "Copy" button, quotes, checkboxes and callouts. `[[wiki-links]]` open the note, and external links use `noopener`. Raw HTML from the model is shown as text (D20). The history and new answers use the same renderer.
- **A2/A3 Core Matrix**: cards up to 1279 px (two columns on tablets), a table from 1280 px. It follows the operator's theme and accent through the design system, and contrast passes AA in both themes.
- **A4 Logs**: removed from git (`logs/.gitkeep`), size rotation (5 MB × 5), `LOG_DIR`.
- **C Tasks**: all tasks now live in **one Obsidian note** (`01 - Projects/🎯 Цели и планы/Задачи.md` by default, configurable per user). Format: `docs/TASKS_FORMAT.md` (Tasks/Dataview emoji, stable `🆔`).
  - Parser: lossless (byte-for-byte round trip, property tests).
  - Writing: one path for every write — lock, then pull, then the operation, then commit as "Second Brain", then push. A rejected push re-applies the *operation*, so nothing is lost.
  - Offline: changes go to an outbox and the task shows as "не синхронизировано".
  - Commands: `sync_tasks` and `export_tasks_to_note` (dry run, idempotent).
  - Tasks UI: edit, delete with confirmation, sync status, Refresh button.
  - Users without a vault keep database tasks. Old database tasks are not lost when a vault is connected (D22).
- **B Production**:
  - Multi-stage Dockerfile: CSS built in node, CPU-only torch, non-root, git included.
  - Entrypoint: wait for the DB, migrate, collectstatic, gunicorn (2 workers, 300 s timeout).
  - Compose: `db`, `web`, `scheduler` (`sync_tasks`) and `tunnel`, with healthchecks (`/healthz/`, `pg_isready`), volumes, no public ports, log rotation, `Europe/Bucharest`.
  - Production settings: refuses an empty or default `SECRET_KEY`, takes hosts and origins from env, sets secure cookies and HSTS; `check --deploy` is clean.
  - Scripts: `deploy/install|update(rollback)|backup|restore|status|migrate-from-old-pc.sh`, systemd units, and `docs/DEPLOY.md` (Russian, step by step).

## R3.2 Not verified live (limits of this environment)
- **Docker:** the Docker daemon was **not started**. Docker Desktop would also start the old production stack (rule 0.3). So there was no image build, no `up`, no live backup/restore, and no `docker kill` restart test. Checked instead: `docker compose config` with a dummy env file, `bash -n` and shellcheck for every script, plus tests for `/healthz/`, `SECRET_KEY`, env settings and `check --deploy`.
- **GitHub:** a push to a real GitHub repository was not tried. All git tests use local bare repositories, including concurrent pushes and two writers in parallel.

## R3.3 What the owner needs to do
1. On the new Ubuntu VM, follow `docs/DEPLOY.md`: fill `.env` (`SECRET_KEY`, `POSTGRES_PASSWORD`, `CLOUDFLARE_TUNNEL_TOKEN`, `GEMINI_API_KEY`, `OLLAMA_HOST`), then run `bash deploy/install.sh`.
2. Create a fine-grained PAT with **Contents: Read and write** for `myObsidian` and enter it in Settings with the repository URL.
3. Move the old data: `deploy/migrate-from-old-pc.sh --dump` (old PC) → `--restore` (server). Then run `export_tasks_to_note --user … --dry-run`, and finally the same command without `--dry-run`.
4. Set the Cloudflare Tunnel public hostname → `http://web:8000`.

## R3.4 Tests and verification
- **Final run** (`start.bat -FullTests -NoServer` → `docs/audit/round3/test-run.txt`): **826 collected — 825 passed, 1 skipped** (the screenshot tool). Breakdown: 474 unit/integration, 52 e2e, 300 responsive.
- **Acceptance:** `tests/acceptance/test_round3.py` has 84 tests and no `xfail`. Start state: `docs/audit/round3/acceptance-start.txt` (79 xfail + 4 guards).
- **Coverage of the new modules:** `tasks_md` 99 %, `tasks_service` 99 %, `vault_writer` 96 %, `sync_tasks` 100 %, `export_tasks_to_note` 93 %, `health` 100 %.
- **Independent verification**, two rounds by separate agents:
  - `VERIFY-1.md`: 2 high defects (restore across schema versions; a duplicate 🆔 hid a task and edits hit the wrong line), 6 medium, 3 low, 3 uncaught mutations.
  - `VERIFY-2.md`: every finding was fixed, but two of the fixes caused regressions (a read-only token combined with duplicate IDs; an unclosed `---`). Those were fixed too.
  - After round 2 I re-ran the mutations that had survived (N2+N16, N3, N13); the tests now catch all three.
  - Bugs B-32…B-48 are listed in `docs/BUGS.md`.
- **Screenshots** at 11 sizes: `docs/audit/round3/responsive/`.

## R3.5 Commits (feature/round3)
08c0701 acceptance tests · b559385 Markdown (A1) · 6ddad30 Core Matrix (A2/A3) · a02f85d logs (A4) · 1c9083f tasks note, writer, cache, outbox (C1–C6) · f8b5900 tasks UI (C7) · 6a47a34 prod image/compose (B1) · 45fbe10 deploy scripts + DEPLOY.md (B2–B4) · 21cb9f4 VERIFY-1 fixes · f1b1c6f VERIFY-2 fixes · (final docs)

# Round 4 — note editor, AI agent + Claude, REST API for the Telegram bot

Branch `feature/round4` (from `feature/round3`). Goals: `docs/audit/round4/GOALS.md`. Method: `docs/audit/PROMPT_LEAN.md`.

## R4.1 What was done
- **D Editor** on the Notes page: CodeMirror 6 (local bundle), Markdown/frontmatter highlighting, preview beside it (tabs «Текст / Просмотр» on phones), `[[` autocomplete, Ctrl+S / Esc, browser drafts. Create from `99 - Templates` (only `tp.date.now` / `tp.file.title` filled in), save with conflict dialog («Моя версия / Версия из хранилища / Скопировать мой текст»), offline queue with a conflict copy, rename with link update in one commit (preview of affected files), delete with confirmation, per-note re-index.
- **E AI**: one provider layer (Gemini chain, Ollama with tool-capable models, **Claude** `claude-haiku-5-5` / `claude-sonnet-5-5`); provider + Claude model in Settings (disabled without `ANTHROPIC_API_KEY`). Chat **"Агент" mode**: 8 tools (no delete), changes only proposed → diff card («Изменения / Итоговый текст», «Применить всё / выбранное / Отклонить», «Откатить» = revert commit), vault rules in the prompt (+ `VAULT_RULES_NOTE`), note text treated as data, 8-step / token limits, content-free logs.
- **API** `/api/v1/` per the **Link2Note contract** (`docs/link2note/`): tokens in Settings (shown once, hash only), scopes read/write/delete/ai with folder rights, rate limit, call log, Idempotency-Key, contract errors, notes from ready Markdown, `lookup` by normalized URL (all contract pairs), list with `fm.*`, byte-exact `PATCH` frontmatter, `PUT`/`DELETE` with `if_sha`, capture (inbox / weekly), tasks, ask, agent. Docs: `docs/API.md`, `docs/DEPLOY.md` §12. Docker network `secondbrain` + alias `secondbrain-web` for the bot.

## R4.2 Tests and verification
- Full run (`docs/audit/round4/test-run.txt`): 974 passed, 1 skipped, 36 xfailed (Round 5 tests), 1 failed — the settings e2e test, fixed right after (ac13fd4) and re-run green. After the review fixes: fast suite re-run (see LOG).
- Acceptance `tests/acceptance/test_round4.py`: 77 tests, **no xfail**. Contract tests `tests/test_api_contract.py` read `docs/link2note/contract/*.json`.
- One independent reviewer (`docs/audit/round4/VERIFY.md`): 1 HIGH (API agent auto-apply bypassed token rights), 5 MEDIUM, 7 LOW; all 5 mutations caught. HIGH + MEDIUM fixed as B-52…B-57 with regression tests.

## R4.3 Not verified live
- No real Gemini / Claude / Ollama calls (all mocked) — Claude model IDs and tool calling should be tried once with a real key.
- No real GitHub push, no Docker build/up (rule 0.3); `docker compose config` checked.
- The bot's own live check (`scripts/check_second_brain_api.py`) was not run against a running site.

## R4.4 What the owner needs to do
1. Optional: `ANTHROPIC_API_KEY` in `.env` → choose Claude in Settings.
2. After deploy: Settings → API tokens → create the bot token (rights and folders: `docs/DEPLOY.md` §12), put it into the bot's `.env`, then run the bot's `scripts/check_second_brain_api.py --all`.
3. If you keep a tag-rules note in the vault, add `fun` there.

## R4.5 Left (LOW, from VERIFY) — candidates for Round 5
Chained offline saves of one note (2nd becomes a conflict copy); duplicate conflict-copy name in the same minute blocks the outbox; web delete/rename without `base_sha`; NFD file names via API; `DELETE /tasks` uses `write` (contract wording says delete); a push that reached GitHub but timed out → retry creates « (2)».

## R4.6 Commits (feature/round4)
d82f0d0 acceptance tests · dce7748 editor (D) · 329d18e providers/agent/UI (E) · c024485 REST API + contract (API) · ac13fd4 settings fix + run log · (review fixes, docs)

# Round 5 — web vault, weekly notes, PWA, 2FA, Obsidian in the browser

Branch `feature/round5` (from `feature/round4`). Goals: `round5/GOALS.md`; decisions D28–D32.

## R5.1 What was done
- Web vault (G-F1/F2): folder tree, Ctrl+K switcher (names + aliases), full-text search with highlight and folder/tag/date filters, tags page, backlinks + unlinked mentions, local/global graph (own SVG layout, simplified on phones), recent/favourites; server render with callouts, clickable task statuses (one commit per click via the writer), embeds/attachments (path-safe), properties panel, KaTeX + Mermaid local; Dataview-lite (own parser, read-only, 2 s / 500 rows, never outside the vault).
- Weekly notes (G-F3): «Эта неделя» opens/creates by the naming rule derived from existing notes, carry-over with diff preview (old tasks → `[>]`, one commit), week calendar. Home dashboard (G-F5). PWA + offline capture queue (G-F4). TOTP 2FA (G-F7). `obsidian` compose profile + DEPLOY §13–14 (G-F6/F7). Owner end-to-end test (G-E2E).
- Continuation session: symlink leak out of the vault closed (B-58: index, RAG loader, get-note by name); R4.5 data LOWs fixed (B-59…B-63); flaky settings e2e (B-64); live check with the Link2Note bot 18/18 (`round5/LINK2NOTE_CHECK.md`); screenshots of changed pages at 375/1024/1440 in `round5/responsive/` (no horizontal overflow).

## R5.2 Tests and verification
- Full run before fixes: 1056 passed / 1 failed (B-64). Fast suite after fixes: 685 passed. Final full run: `round5/test-run.txt`.
- Reviewer: `round5/VERIFY.md` (findings and what was fixed — R5.5).

## R5.3 Not verified live
- Docker: prod image `/healthz/`, bot container `api-health`, the `obsidian` container (daemon not running on this PC).
- Real GitHub vault, real Gemini/Claude answers, Cloudflare Access policies, installing the PWA on a real phone.

## R5.4 What the owner needs to do
- See `docs/audit/SUMMARY_ROUNDS_3-5_RU.md` (merge order, deploy, bot token, `VAULT_BACKEND=api`).

## R5.5 Review findings and leftovers
- `round5/VERIFY.md`: 1 HIGH, 2 MEDIUM, 7 LOW; mutations 4/5 caught (the missed one — per-account 2FA limit — now has a test).
- Fixed with regression tests: HIGH B-65 (admin login → site login with 2FA), MEDIUM B-66 (unsafe URL schemes in rendered notes → `#`),
  MEDIUM B-67 (a stuck outbox row blocks only its own note; the editor gets a clear 409), LOW B-68 (one conflict copy per chain),
  LOW B-69 (2FA row lock + limit test). Re-check of the HIGH by the same short brief: see `round5/VERIFY.md` (re-check section).
- LOW left: capture/append retried after a push that landed but timed out can add the text twice (only note *create* checks its own
  commit); the offline capture queue in localStorage is not cleared on logout (clearing would lose unsent captures; it is keyed by user
  id and never sent for another user); after a session simply expires, cached pages stay until `/login/` is opened online; the Dataview
  2 s limit is per block (a note with hundreds of blocks is slow).
- R4.5 leftovers not done (not data loss): NFD file names via API; `DELETE /tasks` uses the `write` scope (contract wording says delete).
