# Audit log

Format: `[YYYY-MM-DD HH:MM] Phase N · action · result · next step`

[2026-11-10 15:40] Phase 0 · Read repo layout, git log, settings, all Python views/models/rag/git_sync, all templates and JS (~2.7k lines) · Stack confirmed: Django 6.1 + PostgreSQL (docker-compose service `db`); Tailwind v4 CLI; vanilla JS (fetch + JSON APIs). **No HTMX** in the code on `main` (only a remote branch `origin/feature/htmx-migration` exists). Docker daemon is not running; the venv lacks `whitenoise` and `psycopg2` from requirements.txt · next: branch + DB copy
[2026-11-10 15:46] Phase 0 · Created branch `feature/audit` from `main` (6a1d8ee). Copied `ai_manager/db.sqlite3` → `ai_manager/audit_copy_db.sqlite3` (sha256 5ea89448… identical; git-ignored by `*.sqlite3`). The working PostgreSQL DB lives in a Docker volume and was not touched (Docker not even running) · next: deps
[2026-11-10 15:46] Phase 0 · Installed dev deps into project venv: whitenoise==6.9.0 (already pinned in requirements.txt, was missing in venv), pytest-django 4.14.0, pytest-playwright 0.10.0 (playwright 1.65.0). No browser download: Playwright uses the installed MS Edge (`channel=msedge`) · next: settings
[2026-11-10 15:47] Phase 0 · Added `ai_manager/settings_local.py` (SQLite copy, logs → git-ignored local_*.log) and `ai_manager/settings_test.py` (in-memory SQLite, null logging). `manage.py check` → no issues, but takes ~29 s because `core/rag_engine.py` downloads/loads the HuggingFace embedding model at import time (finding → BUGS) · next: migrate copy
[2026-11-10 15:47] Phase 0 · `migrate` on the copy applied missing `core.0006_usersettings_ai_strategy` (copy only) · next: run server
[2026-11-10 15:48] Phase 0 · `runserver --settings=ai_manager.settings_local` on :8765: /login/ 200, /register/ 200, all private pages 302 → /login/?next=…, /admin/ 302, static css 200. Server stopped. No pre-existing tests in the repo (0 test files) · next: CLAUDE.md, pytest config, docs
[2026-11-10 15:52] Phase 0 · Committed b31dff8 and pushed `feature/audit` to origin (push works without prompts) · launched independent Phase-0 verifier subagent (background) · next: Phase 1
[2026-11-10 15:58] Phase 1 · Wrote docs/SITE_MAP.md from direct reading of all code (codebase is small, ~2.7k lines, so it was read in the main context instead of parallel recon agents — recorded as deviation). Added Q1–Q9 to QUESTIONS.md · next: Phase 1 independent verification (code cross-check + Playwright page walk)
[2026-11-10 16:00] Phase 0 · Verifier subagent result: 5/5 PASS (site starts per CLAUDE.md, db.sqlite3 hash unchanged, settings.py identical to main, no tracked files modified, .env untracked). Remarks: CLAUDE.md lacked the DB-copy step / Tailwind location → fixed in CLAUDE.md · Phase 0 done · next: Phase 1 verification
[2026-11-10 16:20] Phase 1 · Verifier subagent (round 1): all 18 routes present; 1 wrong claim (0006 is a data migration), 1 misleading (non-superuser on /system-matrix/ silently lands on /), several omissions (stray "Anti-corruption layer…" text in admin settings rows, JS error handling gaps, home report innerHTML, admin empty temperature 500, base.html malformed). Playwright walk (Edge): all pages 200, no JS errors; only /favicon.ico 404; greeting bug B-05 confirmed · Fixed SITE_MAP, added Q10–Q11 · next: commit, round-2 check
[2026-11-10 16:35] Phase 1 · Round-2 verifier subagent: 3 omissions (chat errors returned as status ok + stored; PAT plain text in .git/config; default retrieval limited to first 10 notes) — added to SITE_MAP §5 and Q12–Q13. No remaining wrong claims → Phase 1 closed (2 rounds) · next: Phase 2 tests
[2026-11-10 16:40] Phase 2 · Wrote tests/conftest.py (HF embedding stub, temp vault, git/ollama network guards), test_models/auth/pages/api/admin_matrix/rag_engine/git_sync: 158 tests; first run 35 failed / 123 passed. 2 failures were test mistakes (shared `client` fixture; wrong 20-char slice) → fixed tests. RAG tests use real LlamaIndex+Chroma in tmp with MockLLM · next: E2E tests
[2026-11-10 16:55] Phase 2 · E2E suite (17 Playwright tests, Edge, live_server) all green; added 2 admin tests; full run saved to docs/audit/test-run-phase2.txt: 177 tests, 142 passed, 35 failed (all = real defects). Wrote docs/TEST_PLAN.md · next: commit, independent test-quality verifier (mutation check)
[2026-11-10 17:05] Phase 2 · Test-quality verifier (worktree, mutation testing): 9 mutations, 6 detected. Survivors: tasks due-date ordering (M5), chat JS dropping selected_files (M7), home report not rendered (M8) — all were missing tests. Weak tests: admin missing-row (accepted 500), sync-failure (too loose) · Added tests: due-date ordering, analytics numbers, e2e selected files reach API, Shift+Enter, status report, home checkbox both directions, admin delete settings row; tightened 2 weak tests (missing-row now requires 404 → new bug B-22) · next: re-verify mutations M5/M7/M8 in round 2
[2026-11-10 17:05] Phase 3 · Fixed so far: B-15 (d2d433d), B-07 (bebe9db), B-10+B-08 (8a0d2b9), B-02 (e61c88f) · next: B-04/B-03/B-11/B-17/B-22
[2026-11-10 17:30] Phase 2 · Round-2 mutation verifier: 5/5 mutations detected (incl. the 3 previous survivors and 2 new). Remark: red-by-design suite needs baseline comparison — handled by D5 (failing set only shrinks; full green required at end of phase 3) → Phase 2 closed
[2026-11-10 17:30] Phase 3 · Fixed B-04 (f26e5e8), B-03 (bd761e3), B-11/B-17/B-22/B-16 (e528431), B-12/B-05/B-20 (8ec5812). Sync-failure test adjusted to pin real behaviour ("Empty Response", Q14). Added red e2e tests for B-18/B-09 (5 failing) · next: B-01 CSRF, B-19, B-09, B-18
[2026-11-10 18:05] Phase 3 · Fixed B-01+B-19 (cd993b9), B-09+B-18 (ae5d8c8). Full suite: 190 passed, 0 failed. BUGS.md completed (18 FIXED, 1 OPEN B-14, 3 QUESTION) · next: independent diff reviewer
[2026-11-10 18:30] Phase 3 · Independent diff reviewer (round 1): all 18 FIXED verified + tests exist; suite 190 passed. Findings: NEW bug from B-12 fix (?next=foo → 500, ?next=logout logs out) → B-23; non-string priority/status 500 + display_name length/atomicity → B-24; notes.js innerHTML sinks → B-25; weak null-settings test. Reviewer's "checkbox not reverted on network error" was incorrect (catch branch already reverted). All fixed test-first; suite 201 passed · next: review round 2
[2026-11-10 18:45] Phase 3 · Review round 2 (independent): B-23/B-24/B-25 fixes correct, "no substantial issues"; minor leftover (display_name/theme/accent length/type) fixed test-first. Suite 204 passed, 1 skipped (screenshot helper, runs only with SCREENSHOT_DIR) → Phase 3 closed
[2026-11-10 18:45] Phase 4 · Added tests/e2e/responsive_helpers.py + test_screenshots.py (11 page states × 5 widths, seeded realistic data, metrics: overflow, tap targets <44px, text <12px, h-scrollers). Captured docs/audit/responsive/before/ (55 PNG + metrics.json) · next: analyse → RESPONSIVE.md
[2026-11-10 19:30] Phase 4 · Analysed before metrics/screenshots: 8 states overflowing (auth blobs, admin), chat section 2 px tall below 1024 (critical), notes 3-pane cramped at 1024, admin tables clipped, Tailwind v4 opacity utilities ignored → solid unreadable badges, register help text black. Fixed R1–R11 (see RESPONSIVE.md), rebuilt styles.css, added tests/e2e/test_responsive.py (71 tests). Full suite 275 passed. After screenshots: 0 overflowing states · next: commit, independent before/after verifier
[2026-11-10 19:55] Phase 4 · Independent before/after verifier (round 1): all pages better, no desktop regressions; responsive suite 71 passed; tap-target metric 653→450 (doc said ~550, corrected). Found REGRESSION from R1: fixed chat modal (and task modal) under the mobile header (z-index stacking) → close button unclickable <1024. Remaining: chat narrow at 1024, md tables unpadded, long-word guard, admin table scroll hint · Fixed R12–R14 test-first, added long-word guard (R15). Full suite 278 passed; after screenshots recaptured (0 overflow) · next: round-2 verification
[2026-11-10 20:20] Phase 4 · Round-2 verifier: R12–R14 fixed, no desktop regressions, responsive 74 passed → Phase 4 closed
[2026-11-10 20:25] Final · Full run → docs/audit/test-run-final.txt: 278 passed, 1 skipped. db.sqlite3 hash unchanged. REPORT.md drafted · next: independent final auditor
[2026-11-10 20:40] Final · Independent final auditor (round 1): SITE_MAP, BUGS refs/hashes, suite (278 passed), DB/secrets, git all PASS; REPORT had 3 wrong numbers (E2E count 28 not 31, "25 fixed" vs 21 fixed/1 open/3 questions, B-14 threshold 128 not ~140) + missing hashes → corrected in REPORT/BUGS/STATUS · next: round-2 check of the corrections
[2026-11-10 20:55] Final · Round-2 auditor: all 7 corrections OK; only nit (279 collected incl. skipped screenshot tool) fixed in REPORT → final verification passed, work complete

## Round 2 (owner answers: docs/audit/PROMPT_ROUND2.md)

[2026-11-10 21:30] R2 · Read PROMPT_ROUND2, REPORT (Safety), QUESTIONS, all code again; baseline fast suite 176 passed · next: before screenshots
[2026-11-10 21:43] R2 §4 · `responsive_helpers.SHOT_SIZES` (11 sizes incl. 667×375); captured `responsive/round2/before/` (121 PNG + metrics; first attempt hit a Playwright timeout, rerun OK) · next: backend
[2026-11-10 21:50] R2 §3 · Model IDs checked in Google's docs (gemini-3.5-flash-lite, gemini-3.8-flash, gemma-4-31b-it; gemini-3.1-flash-lite not confirmed → D13). Found: LlamaIndex GoogleGenAI calls `models.get()` per construction unless max_tokens+context_window are given, and retries 429 three times → disabled (D14) · next: rag_engine rewrite
[2026-11-10 22:00] R2 §1/§3 · settings (DEBUG env, OLLAMA_HOST, GEMINI_*), core/ai_models.py, rag_engine (memory, budget, fallback chain, empty-index messages, last model), migrations 0007–0009, git_sync via GIT_CONFIG_* env, API (report mode, smart, display name, token), admin guard. Updated tests that pinned old behaviour (characterization of Q2/Q6/Q7/Q12/Q14), added new ones; fast suite 242 passed · next: UI
[2026-11-10 22:05] R2 · Commits 758145b (Q13), 2cb8e41 (Q5), 5a76f6a (Q11 + B-26), c52427f (Q1/Q8/Q9), 4a751f6 (Q2/Q3/Q6/Q7/Q12/Q14, B-14, §3). (A pre-staged deletion first slipped into the git-sync commit; split before pushing.)
[2026-11-10 22:10] R2 §4 · Design system in input.css, new shell/sidebar/layout.js, pages rewritten (home, tasks, chat, settings, notes, auth, Core Matrix). Found while testing: component CSS unlayered → overrode utilities (moved into @layer components); desktop modals under the sidebar because `<main>` had z-10 (removed); off-canvas menu Tab-reachable (inert); purple accent 3.9:1 (→ #C77DFF); landscape chat composer off-screen; login/register overflow at 320 px · all fixed
[2026-11-10 22:20] R2 · Full suite 522 passed / 5 failed (2 stale test texts, admin test matched the `disabled:` Tailwind variant, login blob at 320, note XSS test relied on the old loading text) → fixed; targeted reruns green
[2026-11-10 22:26] R2 §2 · start.ps1/start.bat: real runs — `-SkipTests` + server (login 200, static 200; migrations 0007–0009 applied to the audit copy only), fast tests `-NoServer` (242 passed), temporary failing test → server not started, FAIL row in history.csv, fast tests + server; retention 37 → 30 logs. start.bat now keeps the exit code after `pause`. Not run: `-Install`, `-Watch`, `-Tunnel`, `-Docker` (production compose — deliberately not started)
[2026-11-10 22:30] R2 · Commits e3dcb36 (UI), 80bf980 (launcher, .env.example, scripts/list_gemini_models.py — not executed, README, CLAUDE.md). After screenshots → `responsive/round2/after/`: overflow 2 → 0 states, 0 tap targets < 44 px below 1024 px · next: independent responsive verifier (background)
[2026-11-10 22:50] R2 §4 · Independent responsive verifier: 247 responsive tests passed; PARTIAL on light-theme contrast (Settings accent labels 2.3–3.3:1, badge 3.9:1), touch targets at 1024, admin outside the design system; desktop regression in the Notes explorer (identical truncated names); cramped 667×375 chat. Also improved: a failed first sync is retried on the next message (8bcb359)
[2026-11-10 23:00] R2 §4 · Fixed R27–R30 (49ee379); new rendered-contrast test (caught a colour-format parsing bug in my own test first — computed `color(srgb …)` values, now normalised via canvas) and a mutation check; touch-tablet tap test. Admin console styling left (documented) · next: final screenshots, final full run via `start.bat -FullTests -NoServer`, final auditor
[2026-11-10 23:00] Final · Full run via `start.bat -FullTests -NoServer`: 569 passed, 1 skipped (screenshot capture flaked once on a Playwright timeout, rerun OK). Independent final auditor: overall PASS; defects: own-account delete with ids "01"/2.0/" 3" (string comparison), Cyrillic token underestimate, Ollama fallback without re-probe, 500/network errors not falling back, start.ps1 aborts without git, error-only pytest runs recorded 0/0; docs: stale B-14 OPEN section. All fixed test-first in 1afdf64 (a stray backspace char from an escape in my patch script was caught and removed); errors-only launcher path verified with a temporary broken test file · next: final full run, REPORT, push

## Rounds 3–5 (docs/audit/PROMPT_ROUNDS_3-5.md)

### 2026-11-11 14:30 — Round 3 / setup — merge, branch, tools
- `feature/audit` was not in `main` → merged with `--no-ff` (6ed60c4, owner-approved in the brief) and pushed; branch `feature/round3` from it.
- Docker CLI present but the daemon is not running; not started on purpose (existing prod containers have restart policies → would violate rule 0.3). G-B4 will use `docker compose config`, `bash -n`, shellcheck.
- Dev tools into the venv: hypothesis 6.170.15, pytest-cov 7.1.0, shellcheck-py 0.11.0.1 (→ requirements-dev.txt). Front-end libs via npm (marked 15.0.12, dompurify 3.4.17, @highlightjs/cdn-assets 11) copied to `static/vendor/`.
- Files: requirements-dev.txt, ai_manager/package*.json

### 2026-11-11 15:10 — Round 3 / goals — GOALS.md + acceptance tests
- `docs/audit/round3/GOALS.md` (15 goals); `tests/acceptance/test_round3.py` (83 tests), `tests/vault_helpers.py` (bare remote + clones, fictional PARA vault), `tests/acceptance/conftest.py`.
- First run: 4 passed + 79 xfailed (`docs/audit/round3/acceptance-start.txt`). The 4 already true (Auto-Hybrid → Gemini when the LAN PC is off; Core Matrix table at 1280; Core Matrix contrast in both themes) are kept as guards without xfail (GOALS.md). Fixed a test bug: shellcheck-py has no importable module → the test looks for the executable.

### 2026-11-11 15:40 — Round 3 / G-A1 — Markdown in AI answers
- Client renderer `static/js/markdown.js` (marked + DOMPurify + highlight.js, local), wiki-links, callouts, code "Copy", external links, scroll-wrapped tables; chat history ships raw Markdown (`data-markdown`); status report rendered too; Markdown + highlight styles for both themes in `input.css`.
- Files: static/js/markdown.js, static/vendor/{marked,purify,highlight}.min.js, templates/ai-chat.html, templates/home.html, static/js/chat.js, static/js/home.js, static/css/input.css (+styles.css), package.json, tests/test_pages.py, tests/acceptance/test_round3.py
- Checks: acceptance `-k a1` 13 passed; old e2e (errors/flows/round2) 38 passed; fast suite 269 passed, 57 xfailed.
- Deviation: sanitize test refined (D20); `test_chat_page_lists_notes_and_history` updated to the raw-Markdown contract + new escaping test.

### 2026-11-11 16:05 — Round 3 / G-A2, G-A3 — Core Matrix on tablets and in both themes
- Cards below 1280 px (2 columns from 768), fluid table from 1280; console follows the operator theme/accent via tokens; admin.js uses classes instead of hard-coded purple colours.
- Files: templates/admin_dashboard.html, static/css/input.css (+styles.css), static/js/admin.js, core/views/admin.py, tests/e2e/test_responsive_round2.py, tests/acceptance/test_round3.py
- Checks: acceptance `-k "a2 or a3"` 8 passed; admin + e2e admin/matrix 88 passed (2 Round-2 scroll-hint tests replaced, D21); fast suite 270 passed, 56 xfailed.

### 2026-11-11 16:15 — Round 3 / G-A4 — logs outside git, size rotation
- `git rm --cached` for `ai_manager/logs/{rag_engine,system}.log` (the files stay on disk, ignored; old history unchanged — no rewriting), `logs/.gitkeep`, `.gitignore` rules; `RotatingFileHandler` (`LOG_MAX_BYTES` 5 MB × `LOG_BACKUP_COUNT` 5); `LOG_DIR` env, folder created at start.
- Files: .gitignore, ai_manager/logs/.gitkeep, ai_manager/ai_manager/settings.py, tests/acceptance/test_round3.py
- Checks: acceptance `-k a4` 2 passed; fast suite 272 passed, 54 xfailed.

### 2026-11-11 16:25 — Round 3 / part A — full run
- `start.bat -FullTests -NoServer` → 616 passed, 1 skipped, 59 xfailed (log `logs/runs/run_2026-11-11_15-08-30.log`). Part A (G-A1…A4) complete; branch pushed.

### 2026-11-11 17:40 — Round 3 / G-C1…C6 — tasks note, single vault writer, cache, outbox
- Pure parser `core/tasks_md.py`, writer `core/vault_writer.py` (lock → fetch/reset → op → commit → push, re-apply on rejection), `core/tasks_service.py` (cache, interval, outbox, legacy mode), commands `sync_tasks` / `export_tasks_to_note`, migration 0010, API (update fields, delete, sync), `/healthz/`; `docs/TASKS_FORMAT.md`. Modules first written in the scratchpad while the part-A full run was going (a new module mid-run would have made strict-xfail tests pass early).
- Files: ai_manager/core/{tasks_md,vault_writer,tasks_service,git_sync,models}.py, core/management/commands/*, core/migrations/0010_round3_tasks_in_vault.py, core/views/{api,pages,health,__init__}.py, core/urls.py, tests/{test_tasks_md,test_vault_writer,test_tasks_service,test_git_sync,conftest}.py, docs/TASKS_FORMAT.md
- Checks: acceptance C1–C7 39 passed; unit tests 162 passed; coverage tasks_md 99 %, tasks_service 99 %, vault_writer 96 %, sync_tasks 100 %, export command 93 %, health 100 %; fast suite 414 passed.
- Problems: (1) bug in my design found by unit tests — IDs were added before applying ops, so ops addressing ID-less lines by text failed → IDs now after ops (D22); (2) unknown op raised TaskNotFound → ValueError; (3) B-32 (Windows read-only git objects); (4) `two_writers_in_parallel` hit an SQLite-in-memory threading limitation → threads run only the git path (D22); (5) old API contracts kept (list tags still 400, update response unchanged).
- Commit: 1c9083f

### 2026-11-11 17:50 — Round 3 / G-C7 — tasks UI
- Edit/delete (confirm) buttons, shared create/edit dialog, sync status bar + Refresh, "не синхронизировано" badge, allowed-tags hint, Settings field "Tasks note" with the sync/permission error.
- Files: templates/tasks.html, templates/partials/priority_badge.html, templates/settings.html, static/js/{tasks,settings}.js
- Checks: e2e `test_c7_e2e_add_edit_delete_with_confirm` + responsive `test_c7_tasks_page_responsive[*]` passed.
- Commit: f8b5900

### 2026-11-11 18:05 — Round 3 / G-B1…B4 — production config, deploy scripts, DEPLOY.md
- Multi-stage Dockerfile, entrypoint, compose (db/web/scheduler/tunnel), prod settings, `.env.example`/`.env.test.example`, requirements UTF-8 without CUDA; `deploy/*.sh` + systemd units; `docs/DEPLOY.md` (Russian); `.gitattributes` keeps scripts LF.
- Checks: `docker compose --env-file .env.test.example config --quiet` OK (4 services); `bash -n` + shellcheck `-S warning` clean for all scripts; B acceptance tests 21 passed.
- Not checked live: Docker daemon deliberately not started (rule 0.3) → no image build, no `up`, no backup/restore run (D23; owner runs `deploy/install.sh` on the VM).
- Commits: 6a47a34, 45fbe10

### 2026-11-11 18:40 — Round 3 / verification 1 — findings fixed
- Independent verifier (`docs/audit/round3/VERIFY-1.md`): 2 high (restore across schema versions, duplicate 🆔), 6 medium, 3 low; 3 mutations not caught (M1 `..` layer, M8 healthz query, M11 raw HTML as text).
- Fixed B-33…B-43 + tests for M1/M8/M11 (mutation re-check: removing the raw-HTML escape now fails `test_m11_raw_html_from_the_model_is_shown_as_text`); spec gaps closed (C1 unknown-fields acceptance test, coverage + C8 rows in GOALS, DEPLOY §11).
- Files: core/{tasks_md,tasks_service,vault_writer,paths,rag_engine}.py, core/management/commands/sync_tasks.py, core/views/{api,pages}.py, static/js/markdown.js, tests/{conftest,test_round3_regressions}.py, tests/e2e/test_e2e_round3.py, tests/acceptance/test_round3.py, deploy/{restore,update,install}.sh, docker/entrypoint.sh, Dockerfile, docker-compose.yml, .dockerignore, .env.example, docs/{BUGS,DEPLOY}.md, docs/audit/{DECISIONS,round3/GOALS}.md
- Checks: regressions 51 passed + e2e 2 passed; fast suite 466 passed; shellcheck/bash -n clean; compose config OK.
- Problem: during the M11 mutation check a `git checkout --` restored markdown.js to the last commit (losing the uncommitted B-40 hook); the file was restored from the pre-mutation backup and re-verified (hook present, tests green). Lesson: mutate committed files only.

### 2026-11-11 19:20 — Round 3 / verification 2 follow-up
- VERIFY-2 (`docs/audit/round3/VERIFY-2.md`): all VERIFY-1 defects fixed incl. both highs; M1/M8/M11 caught; regressions R1 (read-only token + duplicate IDs → empty list), R2 (unclosed `---` hides tasks); R3 (ERR trap needs `set -E`); R4 test gaps (N2+N16, N3, N13 survived); R5 (sub-items after blank line).
- Fixed as B-44…B-48 with tests; re-ran the surviving mutations myself (backup-copy restore, not `git checkout`): N2+N16 → `test_b34_duplicates_are_kept_apart…` fails, N3 → `test_n3_…` fails, N13 → `test_n13_…` fails (real Windows junction). Spec allows 2 verifier rounds → no third agent round; Round 4's verifier re-checks shared modules.
- Checks: regressions 58 passed; fast suite 474 passed.

### 2026-11-11 19:50 — Round 3 / G-final — DONE
- Final run `logs/runs/run_2026-11-11_16-48-00.log`: 825 passed, 1 skipped (`docs/audit/round3/test-run.txt`); REPORT "Round 3" (R3.1–R3.5), STATUS; branch pushed. Next: Round 4 on `feature/round4`.

### 2026-11-11 20:10 — Round 4 / goals — GOALS.md + acceptance tests
- Branch `feature/round4` from `feature/round3` (0885f78). `docs/audit/round4/GOALS.md` (D1–D6, E1–E6, API1–API6), `tests/acceptance/test_round4.py` (77 tests, scripted fake AI provider, local git repos).
- First run: 77 xfailed (`docs/audit/round4/acceptance-start.txt`). Modules were drafted in the session scratchpad during the Round 3 verification (notes_service, ai_providers, agent, api_v1, weekly) — not yet in the repo.

### 2026-11-11 — Round 4 / part D — notes editor
- Editor (CM6 bundle, preview, `[[` autocomplete, Ctrl+S/Esc, phone tabs), create from template, save with conflicts + offline outbox, rename with link update (one commit), delete, per-note re-index. B-49 (autocrlf), B-50 (e2e serial requests).
- Tests: D acceptance 26 + e2e/responsive 10 passed; fast suite green.

### 2026-11-11 — Round 4 / part E — providers, agent, agent UI
- `core/ai_providers.py` (Gemini chain / Ollama / Claude, one `chat()`), Claude in RAG chat + Settings (provider, model, auto-apply option); `core/agent.py` (8 tools, overlay → batch, apply/reject/revert, rules note, injection-safe results, limits, content-free logs); chat "Агент" toggle + diff card (`agent_chat.js`).
- Tests: E acceptance 26 passed (incl. e2e/responsive), `test_agent_providers.py` 7 passed; fast suite 530 passed; chat e2e 69 passed.

### 2026-11-11 — Round 4 / part API — REST API v1 + Link2Note contract
- `core/api_v1.py` (token auth, rights by path segments, rate limit, call log, Idempotency-Key, contract errors), `url_normalize.py` (port of the bot's normalize), `frontmatter.py` (byte-exact PATCH), tokens in Settings, `/ask` sources + provider, docker network `secondbrain`, `docs/API.md`, DEPLOY §12, contract files in `docs/link2note/`. B-51 (longpaths).
- Tests: `test_api_contract.py` 95 passed with vault_writer; R4 acceptance 63 non-e2e passed, no xfail left; compose config OK.

### 2026-11-11 — Round 4 / end — full run, review, fixes
- Full run 974 passed / 1 failed (settings e2e, fixed ac13fd4) → `round4/test-run.txt`. Reviewer `round4/VERIFY.md`: 1 HIGH, 5 MEDIUM, 7 LOW, 5/5 mutations caught.
- Fixed B-52…B-57 (+ /health no global counters); `tests/test_round4_regressions.py` 12 passed; fast suite 622 passed. Round 5 GOALS + 36 xfail tests ready.

### 2026-11-12 — Round 5 / continuation — goals check, R4.5 LOWs, live bot check
- Full run 1056 passed / 1 failed (settings e2e race, B-64). Goals check: symlink leak out of the vault (B-58, HIGH-ish, fixed with tests). R4.5 data LOWs B-59…B-63 fixed (tests first).
- Live Link2Note check: 18/18 ✅ on copy DB + local temp repo (`round5/LINK2NOTE_CHECK.md`); Docker step skipped (daemon off). Fast suite 685 passed.

### 2026-11-12 — Round 5 / end — review + fixes
- Reviewer `round5/VERIFY.md`: 1 HIGH (admin login skipped 2FA, B-65), 2 MEDIUM (B-66 unsafe link schemes, B-67 stuck outbox), 7 LOW; 4/5 mutations caught.
- Fixed B-65…B-69 with regression tests; re-check of the HIGH by the same brief; final full run → `round5/test-run.txt`. Screenshots `round5/responsive/`.
