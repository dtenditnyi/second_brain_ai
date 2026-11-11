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

## D7. Tailwind v4 opacity utilities (R2)
- Context: templates were written with v3 `bg-opacity-*` classes; the project compiles with Tailwind v4 which removed them → solid badges/nav (unreadable). Not strictly "responsive" but a readability defect on every device.
- Options: (a) convert classes to `/NN` syntax (script `docs/audit/tw4_opacity.py`); (b) add v3-compat CSS (impossible to emulate generically in v4); (c) leave.
- Chosen (a); restores the intended translucent design. Rollback: revert the phase-4 commit.

## D8. Responsive changes are mobile-scoped
- All layout changes use mobile-first classes with the original desktop classes kept behind `lg:`/`xl:`/`md:`; the 44 px control sizing is inside `@media (max-width: 1023.98px)`. Exceptions with desktop effect: R2 colours (intended), notes 3-pane now from 1280 px (was 1024), admin tables get min widths + horizontal scroll.
- `styles.css` rebuilt with `npx @tailwindcss/cli ... --minify` (same as `npm run build`).

---

# Round 2 decisions (owner answers in `docs/audit/PROMPT_ROUND2.md`)

## D9. UI language stays English
- Context: the brief quotes Russian UI strings («Токен сохранён — оставьте пустым…», «Поиск по всему хранилищу», sync error text). The whole interface is English.
- Chosen: English equivalents with the same meaning ("Token saved — leave empty to keep it", "Searching the whole vault", "Selected: N notes", "Could not sync your vault with GitHub — check the repository URL and token in Settings."). Mixing languages in one screen looked broken.
- Rollback: change the strings in `templates/settings.html`, `templates/ai-chat.html`, `static/js/chat.js`, `core/rag_engine.py` (MSG_*).

## D10. Unchecking "done" returns a task to "To Do" (Q10)
- Options: (a) remember the previous status (needs a new column or client state); (b) always `todo`; (c) `in_progress`.
- Chosen (b): no schema change and predictable; every card now also has an explicit To Do / In Progress / Done select, so "back to In Progress" is one click. Validation stays in the existing `/api/update-task/`.

## D11. Display name already existed in `UserSettings` (Q6)
- `UserSettings.display_name` (max 100) was already there but the API copied it into the login. No new column: the API now ignores `username`, validates `display_name` (string, non-empty after strip, ≤ 100) and a data migration (0008) fills empty display names from the username. The login can only be changed by a superuser in Core Matrix.

## D12. PAT without `.git/config` (Q13)
- Options: (a) `GIT_ASKPASS` helper script (needs an executable script on Windows + token in env anyway); (b) tokenised URL then `set_url(plain)` in `finally` (token is on disk during the operation and in the process args); (c) `http.extraHeader` with Basic auth passed through `GIT_CONFIG_COUNT/KEY_0/VALUE_0` env for that one git process (git ≥ 2.31; local git 2.54).
- Chosen (c) + always `set_url(plain_url)` before pull and in `finally` (cleans tokens stored by the old code). Token never touches disk or the command line. Docker image: python:3.12-slim (Debian bookworm) ships git 2.39 → supported.

## D13. Gemini model IDs (section 3)
- IDs from the official Gemini API docs (ai.google.dev models page / Gemma-on-Gemini-API page, checked 2026-11-10): `gemini-3.5-flash-lite` (DEFAULT), `gemini-3.8-flash` (SMART), `gemma-4-31b-it`. `gemini-3.1-flash-lite` was **not confirmed** by the docs search (follows the naming scheme) — it is the first fallback; if it does not exist the chain treats 404 as "unavailable" and moves on. Owner: run `scripts/list_gemini_models.py` and adjust `GEMINI_*` in `.env`.
- Labels and free-tier limits shown in the UI come from `core/ai_models.py` (same IDs as the code, from settings).

## D14. Fallback rules
- Next model on: HTTP 429, `RESOURCE_EXHAUSTED`, "quota"/"rate limit" (→ quota), and 404/`NOT_FOUND`/503/`UNAVAILABLE` (→ model unavailable). Any other error (bad key, invalid request) is **not** masked: it is returned as `System Error: …` immediately.
- After the chain: Auto-Hybrid → Ollama; Cloud Only → "daily limit exhausted" message (or "no configured model answered" if nothing was a quota error). Strictly Local never touches Gemini.
- `GoogleGenAI(max_retries=0, max_tokens=2048, context_window=…)`: no internal retries on 429 (the chain is faster and does not burn RPM), no `models.get()` call per construction.
- The model that answered is logged (`LLM answered: provider=…, model=…`) and stored in `UserSettings.last_model_used/_at` (migration 0009) → indicator on Home, Chat and Settings without any request to Google. Stored per user in the DB because gunicorn runs 3 workers.

## D15. Own retrieval + prompt assembly instead of `as_chat_engine(chat_mode="context")`
- Needed for: the token budget (chunks + history cut to fit), inline system prompt for Gemma, trying several LLMs with the same retrieved context. Retrieval is unchanged (same index, same filters, top-k 5; Gemma uses the first 3).
- Budget: tokens ≈ chars/4; chunks get ≤ 70 % of what remains after system prompt + question, the newest history messages fill the rest; one oversized chunk is truncated instead of dropped. Budgets: Gemma 8000, Gemini 30000, Ollama 6000 (env `PROMPT_TOKEN_BUDGET_*`).
- Gemma: Google's Gemma-4 docs show system instructions working through the Gemini API, but Gemma 3 rejected them; to be safe the system prompt (with the note context) is glued into the first user message for any `gemma*` model.
- Memory: last `CHAT_HISTORY_MESSAGES` (6) rows of the same user, oldest first, read before the new message is stored; "System …" notices are skipped; the list never starts with an AI turn. The status report sends no memory and is not stored.

## D16. Empty index messages (Q14)
- If the user's Chroma collection is empty after the first sync: sync failed → "Could not sync your vault with GitHub — check the repository URL and token in Settings."; sync OK but no `.md` files → "Your vault index is empty…". No LLM call is made. If the pull fails but an older index exists, answers still use it.

## D17. Design system in `input.css` (section 4)
- Runtime theme variables stay (light/dark + accent switch without rebuild) and are exposed to Tailwind with `@theme inline` (`text-fg`, `text-soft`, `text-muted`, `bg-accent/10`, `border-line`, …). Components (`.btn*`, `.field*`, `.badge*`, `.alert*`, `.modal-*`, `.empty-state`, `.spinner`, `.skeleton`, `.typing-dots`) live in `@layer components` so Tailwind utilities can still override them.
- Contrast: `--text-muted` replaces `opacity-50/60` text (5.9:1); the dark purple accent changed `#B026FF` → `#C77DFF` (3.9:1 → 6.1:1); light theme uses dark accent variants (`#0E7490`, `#7E22CE`, `#15803D`). Tested for all 6 theme × accent combinations.
- Core Matrix tables become stacked cards below 768 px (CSS only, `data-label` captions); from 768 px they scroll with scroll-shadow hints.
- Closed off-canvas menu is `inert` below 1024 px (was reachable with Tab).

## D18. Launcher `start.ps1`
- Native commands run through `cmd /c "… 2>&1" | Out-Host` so their output lands in the PowerShell 5.1 transcript without NativeCommandError noise. `.env` is only checked for existence; AI variables are checked in the real environment (a hint says they may still be in `.env`).
- The summary and the `history.csv` row are written before `runserver` starts (the server runs until Ctrl+C); the log is closed after the server stops. `-Docker` asks for "YES" unless `-Force` (production compose). `-NoServer` added for checks-only runs.
- ASCII-only script: PowerShell 5.1 reads BOM-less UTF-8 as ANSI.

## D19. Final-audit adjustments (1afdf64)
- Token estimate: ~4 chars/token for ASCII, ~2 for other scripts (Cyrillic ≈ 2–3), so Russian prompts stay inside the Gemma budget.
- Fallback also on 500/INTERNAL/504/DEADLINE_EXCEEDED and network errors; Auto-Hybrid re-probes Ollama (2 s) before using it as the last fallback (no 600 s hang on an unreachable OLLAMA_HOST).
- The PAT header is scoped to the repository host (`http.https://<host>/.extraHeader`), so git never sends it to another server (e.g. submodules elsewhere).
- Left: `ai_manager/logs/rag_engine.log` is a tracked log file from before the audit that contains the old LAN IP; not changed (pre-existing, owner's call whether to untrack it).

---

# Rounds 3–5 decisions

## D20. Markdown in AI answers: client renderer, raw HTML stays text (R3 / G-A1)
- Question: render where, and what to do with raw HTML the model writes?
- Decision: one client renderer (`static/js/markdown.js`: marked GFM → DOMPurify HTML profile → DOM post-processing) for both new answers and the history (the history ships raw Markdown in `<div data-markdown>`, escaped by Django). Raw HTML in an answer is **escaped and shown as text** (marked `renderer.html`), DOMPurify is a second layer (no SVG/MathML, forbidden `style`/forms/iframes, only http(s)/mailto/relative URLs).
- Why: Markdown needs no raw HTML; showing it as text is what the site did before (Round 1 B-09), keeps the old XSS tests valid, and removes a whole class of sanitizer bypasses. External links get `target=_blank rel="noopener noreferrer"`; `[[wiki-links]]` → `/notes/?file=…` (same tab). Libraries vendored in `static/vendor/` (no CDN).
- Test change (allowed by 0.5.5, the goal was over-specified): `test_a1_markdown_is_sanitized` asserted that the substring `javascript:` never appears in the feed; with raw HTML shown as text the payload `<a href="javascript:…">` legitimately appears as visible text. The test now asserts that no element carries an `on*` attribute or a `javascript:` URL and that no `<svg>`/`<script>` element exists — the actual security criterion. Where: `tests/acceptance/test_round3.py`.

## D21. Core Matrix: cards up to 1279 px, theme-aware console (R3 / G-A2, G-A3)
- Question: cards or hidden columns on tablets? Keep the dark console look?
- Decision: CSS-only cards below 1280 px (one column on phones, two columns 768–1279 px; actions and long text span both); a fluid table (no forced `min-width`) from 1280 px. The page uses the operator's `theme`/`accent` and the shared tokens/components (`btn-solid`, `btn-danger`, `text-muted`, `bg-surface`…); the "console" character stays through the monospace uppercase captions and the 🌌 header.
- Why: hidden columns would hide editable fields (every column is an input); cards keep everything editable without sideways scroll.
- Test change: the Round 2 test `test_core_matrix_scroll_hint_on_tablets` asserted that tables scroll at 834/1024 px — replaced by `test_core_matrix_cards_on_tablets_without_scroll` because G-A2 explicitly changes that requirement. Where: `templates/admin_dashboard.html`, `static/css/input.css` (`.responsive-table`, `.console`), `static/js/admin.js`, `core/views/admin.py` (passes `config`).

## D22. Tasks in one Obsidian note (R3 / G-C1…C7)
- Sections: new tasks go to `## 📥 Входящие` (created before the `🔗 [[…]]` line if missing); the site never moves tasks between sections (status = checkbox, minimal diffs). Default note body has `📥 Входящие`, `🔥 Срочно`, `✅ Выполнено`.
- Priorities: `🔺` urgent, `⏫` high, `🔼` medium, `🔽` low (`⏬` read as low; the original emoji is kept when the line is re-rendered). No emoji = "normal": the cache shows it as medium, and an edit that does not change the priority does not add `🔼`.
- Statuses: `[ ]` todo, `[/]` in progress, `[x]` done (+`✅ date`), `[-]` cancelled (+`❌ date`), `[>]` forwarded; other marks are read as todo and kept verbatim until edited.
- IDs: 6 chars `a-z0-9`; the site pre-generates the ID of a new task so a replayed operation (outbox, retry) is idempotent. Missing/duplicate IDs are fixed on every write, AFTER the operations (an op may address an ID-less line by its exact text — giving it an ID first broke that; found by the unit tests before commit).
- Users without a connected repository keep the database-only tasks (legacy mode, old tests unchanged). After connecting a vault, rows that were never in the note are kept (not deleted by the cache rebuild) until `export_tasks_to_note` moves them.
- Write path: `vault_writer.vault_apply` = file lock `<vault>.lock` (msvcrt/fcntl; shared by all gunicorn workers on the host and by `git_sync`) → `fetch` + `reset --hard origin/<branch>` (the local clone is only a cache) → operation → commit as "Second Brain" → push; on a rejected push the same operation is re-applied to the new state (VAULT_PUSH_RETRIES=4). Postgres advisory locks were not needed: all workers share one host and one volume.
- Errors: offline → outbox + "не синхронизировано"; permission → message naming "Contents: Read and write" (stored in `tasks_sync_error`, shown on Tasks and Settings); task deleted elsewhere → cache refreshed + clear message.
- Test change: `test_c3_two_writers_in_parallel` originally ran `add_task` in two threads; the in-memory SQLite test DB raised "database table is locked" (SQLite limitation, Postgres in prod handles it). The threads now run only the git write path (`vault_apply`) and push at the same moment (barrier); the test additionally asserts a rejected-and-retried push — the actual criterion (parallel pushes, nothing lost).

## D23. Production configuration (R3 / G-B1…B4)
- `requirements.txt` converted from UTF-16 to UTF-8 and the CUDA/NVIDIA/triton wheels removed (a GPU stack is useless on the VM and multi-GB); the image installs CPU-only `torch==2.13.0` from the PyTorch CPU index first.
- Scheduler: a compose service (`scheduler`) running `manage.py sync_tasks --all --if-stale` every `TASKS_SYNC_INTERVAL` s (no systemd timer needed; restarts with the stack).
- No top-level `name:` in compose: the project name stays the folder name so existing volumes (`second_brain_ai_postgres_data`) are reused; no `container_name` (avoids clashes with the old stack). The tunnel token is passed as `TUNNEL_TOKEN` env instead of the command line (not visible in `ps`).
- Security: SECRET_KEY empty/default → `ImproperlyConfigured` when DEBUG=False (dev/test settings set `SECONDBRAIN_DEV_SETTINGS`); secure cookies, HSTS 1 year incl. subdomains, SSL redirect with `/healthz/` exempt (Docker healthcheck is plain http). `security.W021` (HSTS preload) silenced: preloading is a one-way commitment for the domain → opt-in via `SECURE_HSTS_PRELOAD`.
- Docker daemon not started on this PC (rule 0.3: the old prod stack has restart policies). Verified offline instead: `docker compose config` with `.env.test.example` (`--env-file` so the real `.env` is never read for interpolation), `bash -n`, shellcheck (`-S warning`), unit/acceptance tests for `/healthz/`, SECRET_KEY, env settings, `check --deploy`.
- Test fixes before implementation (not weakening): `check --deploy` test used `"k"*64` as SECRET_KEY, which Django correctly flags (W009) → realistic random test key; the conftest's `DJANGO_ALLOW_ASYNC_UNSAFE` (Playwright) leaked into the subprocess → stripped there; `/healthz/` test lacked DB access → `db` fixture.

## D24. Fixes after VERIFY-1 (Round 3)
- External images in AI answers are not loaded at all (only same-site paths); a link is shown instead (B-40). A CSP was considered but would also need nonce work for the inline scripts in the templates — left for Round 5 (F7 security pass).
- Duplicate IDs: fixed by a write at sync time (one commit) rather than only "on the next write" — correctness of the cache beats "no commit on read" (B-34).
- Tags from Obsidian that are not in the allowed list are kept on edit; the allowed list applies to tags the site adds (B-35).
- Scheduler: one long-lived `sync_tasks --loop` process instead of a new process per minute (B-38).
