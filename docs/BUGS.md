# BUGS

Order: whole-site breakers → functional → security → minor. Each fix: red test → code → green → full suite (no new failures, D5) → commit. End of phase 3: **190 passed, 0 failed**.
Status: **FIXED** (commit) · **OPEN** (not solved, with analysis) · **QUESTION** (behaviour kept, see `docs/audit/QUESTIONS.md`).

| ID | Severity | Title | Test(s) | Status |
|---|---|---|---|---|
| B-15 | site | Embedding model downloaded/loaded at import → slow start, start fails without HF access | `test_rag_engine::test_import_does_not_load_embedding_model_eagerly` | FIXED d2d433d |
| B-07 | site | Every page 500 when user has no `UserSettings` row | `test_pages::test_pages_work_for_user_without_settings_row[*]`, `test_admin_matrix::test_admin_delete_settings_row_then_user_pages_still_work` | FIXED bebe9db |
| B-10 | functional + privacy | LLM is process-global (`Settings.llm`): a user can be answered by another user's provider (Strictly Local → Gemini) | `test_rag_engine::test_each_user_keeps_own_llm` | FIXED 8a0d2b9 |
| B-08 | functional | `reset_chat_engine(uid)` wipes all users' caches when uid has no engine | `test_rag_engine::test_reset_chat_engine_for_uncached_user_keeps_other_users_cache` | FIXED 8a0d2b9 |
| B-02 | functional | Malformed JSON → 500 in all JSON POST APIs | `test_api::*malformed_json*` | FIXED e61c88f |
| B-04 | functional | Task APIs: bad input → 500 / invalid data; GET update-task → 500 | `test_api::test_add_task_invalid_payload_returns_400[*]`, `test_update_task_*` | FIXED f26e5e8 |
| B-03 | functional | Save settings: empty username saved (lock-out), taken username → 500, nulls → 500 | `test_api::test_save_settings_empty_username_rejected`, `..._taken_...`, `..._null_values_...` | FIXED bd761e3 |
| B-11 | functional | Admin APIs redirect non-superusers to non-existent `/accounts/login/` | `test_admin_matrix::test_admin_api_forbidden_for_normal_user[*]` | FIXED e528431 |
| B-17 | functional | Core Matrix: empty temperature → 500 | `test_admin_matrix::test_admin_update_settings_empty_temperature_is_not_500` | FIXED e528431 |
| B-22 | functional | Core Matrix: unknown row id → 500 with exception text | `test_admin_matrix::test_admin_update_missing_row_is_error` | FIXED e528431 |
| B-16 | minor | Stray text "Anti-corruption layer code entry point" in Core Matrix settings rows | `test_admin_matrix::test_dashboard_has_no_stray_debug_text` | FIXED e528431 |
| B-12 | functional | Login ignores `?next=` | `test_auth::test_login_respects_next_parameter`, `..._ignores_external_next` | FIXED 8ec5812 |
| B-05 | functional | Chat greeting never shown | `test_pages::test_chat_greeting_shown_when_history_empty` | FIXED 8ec5812 |
| B-20 | security | Wiki-link target/alias unescaped in HTML attribute | `test_api::test_get_note_wikilink_target_is_attribute_escaped` | FIXED 8ec5812 |
| B-01 | security | All state-changing JSON endpoints `@csrf_exempt` | `test_api::test_state_changing_api_requires_csrf_token[*]`, `..._accepts_csrf_header`, `test_admin_matrix::test_admin_delete_requires_csrf`, all E2E flows (token sent by JS) | FIXED cd993b9 |
| B-19 | minor | `base.html` `#app-wrapper` unclosed, scripts after `</body>` | `test_pages::test_base_layout_html_is_well_formed` | FIXED cd993b9 |
| B-09 | security | AI replies / user text inserted with `innerHTML` (chat, home report) | e2e `test_e2e_errors::test_chat_reply_is_rendered_as_text`, `..._home_report_is_rendered_as_text` | FIXED ae5d8c8 |
| B-18 | functional (UX) | JS ignores API errors (add task, settings, chat, checkbox) | e2e `test_e2e_errors::test_settings_save_error_is_shown`, `..._add_task_error_is_reported`, `..._chat_api_error_message_is_shown` | FIXED ae5d8c8 |
| B-13 | security (design) | GitHub PAT rendered into settings page HTML | characterization `test_pages::test_settings_page_echoes_github_token_into_html` | QUESTION Q7 |
| B-21 | security (design) | PAT stored in plain text in vault `.git/config` | — | QUESTION Q13 |
| B-14 | latent | Encrypted token can exceed `max_length=255` | — | OPEN |
| B-06 | note | "Generate Status Report" stores prompt/answer in chat history | — | QUESTION Q3 |

## Details

### B-15 — embedding model loaded at import
- Repro: `manage.py check` took ~29 s and printed HF download warnings; offline, every process start (incl. gunicorn workers) fails at `HuggingFaceEmbedding(...)` in `core/rag_engine.py`.
- Cause: `Settings.embed_model = HuggingFaceEmbedding(...)` at module level; `core.views.pages` imports `rag_engine`, so URL loading triggers it.
- Options: (1) lazy `ensure_embed_model()` on first chat request; (2) load in `AppConfig.ready()`; (3) env flag to skip.
- Chosen (1) — same model/vectors, smallest change (D6). Result: `check` ~8 s. Trade-off: first chat message per process is slower.

### B-07 — missing settings row crashes pages
- Repro: Core Matrix → Settings → Drop a row → that user gets 500 (`RelatedObjectDoesNotExist`) on every page.
- Cause: `user.settings` accessed directly in `utils.get_user_config`, `notes_view`, `api_save_settings`, `rag_engine`.
- Options: (1) `get_user_settings()` helper that recreates defaults; (2) forbid deleting settings rows in admin API; (3) middleware.
- Chosen (1); (2) would still leave legacy users broken.

### B-10 — global LLM shared across users (privacy)
- Repro (test): user A cloud_only asks, user B local_only asks, user A asks again → A's engine was built with B's Ollama LLM (and vice-versa: a Strictly Local user's notes can be sent to Gemini).
- Cause: LLM stored in process-global `Settings.llm`; the cached index builds a new chat engine for every message from `Settings.llm`.
- Options: (1) per-user `_user_llms` dict passed as `llm=` to `as_chat_engine`; (2) lock + re-assign `Settings.llm` before each chat; (3) cache the engine and stop rebuilding it (changes Q2 behaviour).
- Chosen (1). `Settings.llm` is still assigned for backwards compatibility.

### B-08 — cache reset clears everybody
- Cause: `else` branch of `reset_chat_engine` ran for any uid not in `_user_chat_engines`. Fixed: per-user `pop` when uid given; full clear only for `reset_chat_engine()`.

### B-02 — malformed JSON → 500
- Fix: `utils.parse_json_body()` returns None for invalid JSON / non-object; all 6 JSON POST views answer 400.

### B-04 — task API validation
- Repro: `POST /api/add-task/ {}` → IntegrityError 500; `due_date:"x"` → ValidationError 500; `priority:"galactic"` stored; `GET /api/update-task/` → "view didn't return an HttpResponse" 500; `status:"exploded"` stored.
- Fix: validate title (non-blank, ≤255), priority/status in model choices, tags ≤100, ISO date, integer id; 400 with `msg`. Title is stored stripped (minor change).
- Alternative considered: Django `ModelForm` — more invasive.

### B-03 — save-settings username
- Repro: clear "Display Name" and save → username becomes `""` → user can't log in; set it to another user's name → IntegrityError 500; `{"github_repo_url": null}` → AttributeError 500.
- Fix: nulls keep stored values; empty / too long / taken username → 400 with message. Renaming via display name itself kept (Q6). Not added: Django's username character validator (would newly reject display names with spaces — behaviour change).

### B-11 / B-17 / B-22 / B-16 — Core Matrix
- B-11: `user_passes_test(..., login_url='login')` on the APIs (page already had it).
- B-17: empty temperature keeps the stored value; non-numeric → 400.
- B-22: `ObjectDoesNotExist` → 404 instead of 500 with exception text.
- B-16: removed the stray literal text from `admin_dashboard.html` (left from 1947df4).

### B-12 — login `?next=`
- Fix: redirect to `next` only if `url_has_allowed_host_and_scheme` (same host) — external targets fall back to home (test).

### B-05 — chat greeting
- Cause: `reversed(queryset)` iterator is always truthy. Fix: `list(reversed(...))`.

### B-20 — wiki-link attribute injection
- Repro: a note with `[[a" onmouseover="alert(1)]]` produced an anchor with an `onmouseover` attribute. Fix: `html.escape` target and display text. Raw HTML inside the Markdown body is still passed through (own notes; Markdown feature) — not changed.

### B-01 — CSRF
- Repro: any site could POST JSON to `/api/admin/delete-row/`, `/api/save-settings/` etc. with the victim's session cookie.
- Fix: removed `@csrf_exempt` (6 views); `base.html` / `admin_dashboard.html` render `<meta name="csrf-token">` and load new `static/js/csrf.js`; every JSON POST sends `X-CSRFToken`. `CSRF_TRUSTED_ORIGINS` already contains the production domain (login forms used CSRF already).
- Options: (1) header token (chosen); (2) `SameSite=Strict` cookies only (weaker, changes login across tunnel); (3) keep exempt (no).
- Rollback: revert cd993b9.

### B-19 — base layout markup
- Closed `#app-wrapper`, moved scripts inside `<body>`. The duplicated inline mobile-menu script was kept (harmless duplicate of `layout.js`).

### B-09 — innerHTML of AI/user text
- Fix: `window.escapeHtml()` before inserting text in `chat.js` (`appendMessage`, `updateMessage`) and `home.js` (report). Same result as the server-rendered history (`linebreaksbr` escapes). Note: Markdown in AI replies is shown as plain text (it was never rendered as Markdown before either).

### B-18 — JS error handling
- settings: shows `Error: <msg>` then resets; add-task: alert with server message, modal stays; task checkbox: reverted on HTTP error; chat: shows `⚠️ <msg>` instead of a misleading "connection failed".

### B-14 — OPEN: encrypted token length
- Analysis: Fernet output ≈ `4/3·(57 + 16·ceil((n+1)/16))` chars. Classic `ghp_` (40) and fine-grained `github_pat_` (93) tokens → ~140–204 chars: fit. Tokens > ~140 chars would exceed 255 → `value too long` on PostgreSQL (SQLite does not enforce; not reproducible in the test DB).
- Options: (1) migration `max_length=500`; (2) `TextField`; (3) leave. Not applied: schema migration on the production DB is a decision for the owner and current GitHub tokens fit. Status: OPEN.

### B-13 / B-21 / B-06 — QUESTIONS
Kept as-is, documented in QUESTIONS (Q7, Q13, Q3) and pinned by characterization tests where testable.
