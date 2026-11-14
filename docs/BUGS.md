# BUGS

Order: whole-site breakers → functional → security → minor. Each fix: red test → code → green → full suite (no new failures, D5) → commit. End of phase 3 (after review rounds 1–2): **204 passed, 0 failed** (+1 skipped screenshot helper).
Status: **FIXED** (commit) · **OPEN** (not solved, with analysis) · **QUESTION** (behaviour kept, see `docs/audit/QUESTIONS.md`).
**Round 2 (owner answers):** all former QUESTION items and B-14 are fixed; B-26…B-31 added. Responsive/visual items of Round 2 are R16+ in `docs/audit/RESPONSIVE.md`.

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
| B-23 | functional (regression of B-12 fix, found by reviewer) | `POST /login/?next=foo` → 500 (`redirect()` tried `reverse('foo')`); `?next=logout` logged the user out right away | `test_auth::test_login_with_odd_next_values_is_safe[*]` | FIXED 2fc5f6c |
| B-24 | functional (review) | Non-string `priority`/`status` (list/dict) → `TypeError` 500; dict/list title stored as repr; 101–150-char name → DataError on Postgres (`display_name` max 100); user+settings saves not atomic; (round 2) over-long / non-string display_name, theme, accent_color → DataError on Postgres | `test_api::test_add_task_invalid_payload_returns_400[payload6-8]`, `test_update_task_rejects_non_string_status`, `test_save_settings_name_longer_than_display_name_field_rejected`, `test_save_settings_rejects_overlong_or_non_string_preferences[*]` | FIXED 2fc5f6c + faf211a |
| B-25 | security, low (review) | `notes.js` inserts note name, backlink title/snippet and error msg via `innerHTML` unescaped | e2e `test_e2e_errors::test_note_names_and_backlinks_are_rendered_as_text` | FIXED 2fc5f6c |
| B-13 | security (design) | GitHub PAT rendered into settings page HTML | `test_pages::test_settings_page_never_contains_github_token`, `test_api::test_empty_token_field_keeps_saved_token`, `..._clear_token_checkbox_removes_token`, e2e `test_e2e_round2::test_token_field_is_empty_and_keeps_or_clears_token` | FIXED (Round 2) 4a751f6 + e3dcb36 |
| B-21 | security (design) | PAT stored in plain text in vault `.git/config` | `test_git_sync::test_pull_leaves_no_token_in_git_config[*]`, `..._clone_leaves_no_token_in_git_config[*]`, `..._failure_after_tokenised_url_is_cleaned_in_finally`, `..._real_git_accepts_env_header_config` | FIXED (Round 2) 758145b |
| B-14 | latent | Encrypted token can exceed `max_length=255` | `test_api::test_long_token_is_stored_and_read_back`, `..._overlong_token_rejected_without_partial_save` | FIXED (Round 2) 4a751f6 (migration 0007) |
| B-06 | note | "Generate Status Report" stores prompt/answer in chat history | `test_api::test_status_report_is_not_stored_and_uses_smart_model`, e2e `test_e2e_round2::test_smart_toggle_and_report_mode` | FIXED (Round 2) 4a751f6 |
| B-26 | functional (Round 2) | Core Matrix: saving a user row without `is_superuser` silently removed superuser rights | `test_admin_matrix::test_missing_superuser_key_does_not_demote` | FIXED 5a76f6a |
| B-27 | functional (Round 2) | Superuser could demote / delete themself in Core Matrix (Q11) | `test_admin_matrix::test_superuser_cannot_*`, `..._own_row_controls_are_disabled_in_ui`, e2e `test_core_matrix_own_row_is_protected` | FIXED 5a76f6a + e3dcb36 + 1afdf64 |
| B-28 | functional (Round 2) | Display Name renamed the login (Q6) | `test_api::test_save_settings_display_name_does_not_rename_login`, e2e `test_display_name_change_keeps_login` | FIXED 4a751f6 |
| B-29 | functional (Round 2) | Chat searched only the first 10 notes by default (Q12) | `test_pages::test_chat_page_preselects_nothing_and_searches_whole_vault`, e2e `test_chat_sends_selected_context_files_to_api` | FIXED 4a751f6 + e3dcb36 |
| B-30 | functional (Round 2) | First chat after a failed sync answered "Empty Response" (Q14) | `test_rag_engine::test_ask_sync_failure_explains_instead_of_empty_response`, `..._empty_vault_after_successful_sync` | FIXED 4a751f6 |
| B-32 | functional (Round 3) | Re-cloning after an interrupted clone failed on Windows: `shutil.rmtree` cannot delete read-only git object files | `test_git_sync::test_incomplete_clone_with_read_only_files_is_removed`, `test_vault_writer::test_pull_resets_local_junk_and_recovers_broken_clone` | FIXED (Round 3, part C commit) |
| B-44 | functional (R3 verify 2, regression of B-34) | Read-only token + duplicate IDs → sync error, empty task list | `test_b44_read_only_token_with_duplicate_ids_still_shows_tasks` | FIXED |
| B-45 | data (R3 verify 2, regression of B-41) | Note starting with an unclosed `---` lost every task | `test_b45_unclosed_leading_dashes_are_not_frontmatter[*]` | FIXED |
| B-46 | deploy (R3 verify 2) | `update.sh` ERR trap never fired inside shell functions (no `set -E`) | `test_b46_update_script_fires_err_trap_inside_functions` | FIXED |
| B-47 | tests (R3 verify 2) | Test gaps: duplicate cache fix (N2+N16), sync repair (N3), junction to `.git` (N13) | `test_b34_duplicates_are_kept_apart…` (2 syncs), `test_n3_…`, `test_n13_…` — mutations re-run and caught | FIXED |
| B-48 | data (R3 verify 2) | Deleting a parent left sub-items that follow a blank line | `test_b48_delete_parent_with_blank_line_inside_subitems` | FIXED |
| B-33 | data (R3 verify) | `restore.sh` of an older dump (old PC, fewer tables) failed half-way and left a half-dropped DB | `test_round3_regressions::test_b33_restore_recreates_schema_in_one_transaction` (static; no Postgres here) | FIXED (R3 fix commit) |
| B-34 | data (R3 verify) | Duplicate 🆔 (line copied in Obsidian) hid one task and edits hit the wrong line | `test_b34_duplicate_id_does_not_hide_a_task_or_edit_the_wrong_line`, `test_b34_duplicates_are_kept_apart_even_when_the_fix_cannot_be_pushed` | FIXED |
| B-35 | functional (R3 verify) | Task with a tag outside the allowed list (from Obsidian) could not be edited; `[[#Heading]]` parsed as a tag | `test_b35_*` (3) | FIXED |
| B-36 | security (R3 verify) | `safe_path` bypass on Windows: `.GIT/`, `.git./`, `.Obsidian/`, `CON`, `x.md::$DATA`, trailing dots | `test_b36_windows_tricks_rejected[*]`, `test_b36_tasks_note_path_cannot_point_into_git`, `test_m1_dotdot_layer_rejects_on_its_own` | FIXED |
| B-37 | security (R3 verify) | `.dockerignore` root-only patterns → `ai_manager/db.sqlite3`, `.coverage` would ship in the image | `test_b37_*` (19, Docker matching rules) | FIXED |
| B-38 | performance (R3 verify) | Scheduler imported torch/llama_index every minute (`vault_writer` → `rag_engine`) | `test_b38_task_sync_does_not_import_torch`, `test_b38_sync_loop_keeps_one_process`, `test_b38_loop_survives_a_failing_round` | FIXED |
| B-39 | deploy (R3 verify) | `update.sh` said "already up to date" after a failed build | `test_b39_update_remembers_deployed_commit_and_resets_on_error` (static) | FIXED |
| B-40 | security (R3 verify) | AI answers loaded external images (exfiltration via prompt injection) | e2e `test_e2e_round3::test_b40_external_images_in_ai_answers_are_not_loaded` | FIXED |
| B-41 | data (R3 verify) | Parser edge cases: deleting a parent orphaned sub-tasks; nested fences; frontmatter `# comment` as section; protected branch retried as conflict | `test_b41_*` (4) | FIXED |
| B-42 | hardening (R3 verify) | Image: code writable by the app user, tests shipped, cloudflared unpinned | `test_b42_code_is_not_writable_by_the_app_user` | FIXED (cloudflared: configurable `CLOUDFLARED_IMAGE`, pin documented) |
| B-43 | docs (R3 verify) | `.env.example` WEB_BIND claimed LAN access works over http; Docker bypasses ufw | — (doc) | FIXED |
| B-31 | config (Round 2) | DEBUG hard-coded True, LAN-IP default for OLLAMA_HOST, settings label "Gemini 2.5 Flash" vs code `gemini-3.6-flash` (Q1, Q8, Q9) | `test_debug_static::*`, `test_rag_engine::test_ollama_url_from_settings_with_localhost_default`, `..._no_hardcoded_lan_ip_in_code`, `test_pages::test_settings_dropdown_shows_real_model_names_and_limits` | FIXED c52427f + e3dcb36 |

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

### B-23 / B-24 / B-25 — found by the independent phase-3 reviewer
- B-23: `next` is accepted only if it starts with `/` and passes `url_has_allowed_host_and_scheme`, returned via `HttpResponseRedirect` (no `reverse()`); bare words go to home.
- B-24: type checks for title/tags/priority/status; username limited to min(150, display_name 100); `api_save_settings` wrapped in `transaction.atomic`.
- B-25: `window.escapeHtml` for the note name, backlink title/snippet and error message in `notes.js` (Markdown body still rendered as HTML — own notes).

### B-14 — encrypted token length (Round 1 analysis; superseded — fixed in Round 2, see below)
- Analysis: Fernet output ≈ `4/3·(57 + 16·ceil((n+1)/16))` chars. Classic `ghp_` (40) and fine-grained `github_pat_` (93) tokens → ~120–204 chars: fit. Tokens of ≥ 128 chars encrypt to ≥ 268 chars and would exceed 255 (≤ 127 → ≤ 248, fits) → `value too long` on PostgreSQL (SQLite does not enforce; not reproducible in the test DB).
- Options: (1) migration `max_length=500`; (2) `TextField`; (3) leave. Round 1: not applied (owner decision). **Round 2: fixed by migration 0007, see "B-14 — fixed in Round 2".**

### B-13 / B-21 / B-06 — were QUESTIONS, fixed in Round 2
- B-13 (Q7): the settings page renders an empty password field; placeholder/hint "Token saved — leave empty to keep it"; empty value keeps the token, the explicit "Delete the saved token" checkbox (`clear_github_token`) removes it.
- B-21 (Q13): token passed only to the git process via `GIT_CONFIG_*` env (`http.extraHeader`, Basic auth), origin always reset to the plain URL (before pull and in `finally`), see DECISIONS D12.
- B-06 (Q3): Home sends `mode: "report"`; the API does not store the prompt/answer and sends no memory; SMART model.

### B-14 — fixed in Round 2
- Migration `0007_alter_usersettings_github_token_length` (`max_length=500`); the API rejects tokens > 255 plain characters before any write (they would still fit, but no real PAT is that long).

### B-26 … B-31 — Round 2
- B-26: `api_admin_update_row` set `is_superuser = fields.get('is_superuser') in ['true', True]`, so a request without the key demoted the user. Now only changed when the key is present.
- B-27 (Q11): backend refuses removing your own superuser flag (400) and deleting your own user row (400). The final auditor found that ids like `"01"`, `2.0` or `" 3"` slipped past the first string comparison → now the id is normalised once (int or digit string, else 400) and used for both the guard and the delete (1afdf64, `test_superuser_cannot_delete_own_account_with_odd_id_formats[*]`); Core Matrix settings rows are validated too; the template disables both controls for the own row; `admin.js` skips disabled controls.
- B-28 (Q6): `username` in the save-settings payload is ignored; `display_name` validated (string, non-empty after strip, ≤ 100). Data migration 0008 fills empty display names. Sidebar/greeting/system prompt use the display name.
- B-29 (Q12): no pre-checked notes; empty selection = whole vault; UI shows "Searching the whole vault" / "Selected: N notes" + Reset.
- B-30 (Q14): see DECISIONS D16.
- B-31: DEBUG from env (default off), OLLAMA_HOST env-only (default localhost), model labels from `core/ai_models.py`.

### B-32 — Round 3: interrupted clone could not be removed on Windows
- Symptom: after an interrupted clone, the next sync tried `shutil.rmtree(local_dir)` and failed with `PermissionError: [WinError 5]` on read-only files in `.git/objects` → the vault never re-synced until the folder was deleted by hand.
- Cause: git marks object files read-only; `rmtree` does not clear the flag on Windows.
- Fix: `vault_writer.remove_tree` (rmtree with an `onexc` handler that makes files writable), used by `git_sync` and `VaultRepo.pull`. Regression tests above. Found by the new vault-writer unit tests.

### B-33 … B-43 — found by the independent Round 3 verifier (`docs/audit/round3/VERIFY-1.md`)
- B-33: `restore.sh` now runs `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` + the dump through one `psql --single-transaction -v ON_ERROR_STOP=1`; migrations to the current version run when web starts.
- B-34: duplicates are detected on read → one "tasks: …" commit gives the copies new IDs; if that cannot be pushed (offline), the cache keeps repeated IDs apart by their line.
- B-35: only newly added tags are validated (in `tasks_service.update_task` and `tasks_md.apply_op`); `#` right after `[` or `|` is not a tag.
- B-36: parts compared case-insensitively, trailing dots/spaces, `:`, control chars and Windows device names rejected, the resolved path is checked again.
- B-37: `**/` patterns, tests and backups excluded; a test evaluates Docker's matching (last rule wins) on real paths.
- B-38: `core/paths.py` (light) replaces the `rag_engine` import in the writer/pages; the scheduler runs `sync_tasks --loop` (one process, survives failing rounds).
- B-39: `.deployed_commit` + `trap … ERR` resetting the checkout.
- B-40: DOMPurify hook removes non-local `src` while sanitising (inert document → no request); a plain link is shown instead.
- B-41: sub-items are deleted with their parent; fences close only with the same char and ≥ length; frontmatter skipped; "protected branch"/GH006 → permission.
- B-42/B-43: see table.
| B-49 | data (R4 / D) | Git for Windows `core.autocrlf=true` gave the editor CRLF text → hash/diff mismatch and CRLF commits from the site | `test_round4::test_d1_raw_note_has_content_and_hash`, `test_vault_writer::test_repo_clone_pull_commit_push_cycle` (byte-exact) | FIXED (R4 part D) |
| B-50 | tests (R4 / D) | e2e: live_server shares one in-memory SQLite connection; parallel requests (note + editor names) failed with `InterfaceError` | test-only `tests/serial_middleware.py` in `settings_test`; D e2e stable | FIXED (R4 part D) |
| B-51 | functional (R4 / API) | Git for Windows: notes with long names in deep folders failed to commit ("Filename too long") | `test_api_contract::test_create_writes_markdown_as_is_and_suffixes_names` (120-char name); `core.longpaths=true` pinned per clone | FIXED (R4 part API) |
| B-52 | security (R4 verify, HIGH) | `POST /api/v1/agent` with an ai-only token auto-applied additions (Settings option), bypassing `write` + `write_paths` | `test_round4_regressions::test_b52_api_agent_never_auto_applies` | FIXED |
| B-53 | security (R4 verify) | API revert checked only the `write` scope, not paths / `delete` for created notes | `test_b53_api_revert_checks_paths` | FIXED |
| B-54 | data (R4 verify) | Revert failing half-way left reverted shas in the batch → second revert stuck | `test_b54_partial_revert_is_not_repeated` | FIXED |
| B-55 | data (R4 verify) | PATCH frontmatter wrote unquoted YAML (`a: b`, `#x`, `[a`) → Obsidian dropped properties | `test_b55_frontmatter_values_are_yaml_safe[*]` | FIXED |
| B-56 | data (R4 verify) | Rename rewrote linking CRLF notes as LF (whole-file diffs) | `test_b56_rename_keeps_crlf` | FIXED |
| B-57 | data (R4 verify) | Rename rewrote `[[Name]]` pointing to another note with the same name; case-sensitive link match | `test_b57_rename_ambiguous_names_and_case` | FIXED |
| B-58 | security (R5 goals check) | Symlinked `.md`/folders in a vault were read by search/Dataview/graph, RAG and get-note by name → files outside the vault (another user's clone) could leak | `test_index_skips_symlinks_leaving_the_vault`, `test_rag_loader_and_get_note_skip_symlinks` | FIXED |
| B-59 | data (R4.5 LOW) | Chained offline saves of one note: the 2nd became a conflict copy | `test_chained_offline_saves_of_one_note_apply_in_order` | FIXED |
| B-60 | data (R4.5 LOW) | Two conflict copies in one minute → «already exists» stalled the outbox forever | `test_two_conflict_copies_in_one_minute_do_not_block_outbox` | FIXED |
| B-61 | data (R4.5 LOW) | Resent save with old base after a lost response → false conflict | `test_resent_save_after_lost_response_is_not_a_conflict` | FIXED |
| B-62 | data (R4.5 LOW) | Web delete/rename ignored edits made elsewhere since the page was opened | `test_web_delete_and_rename_refuse_a_changed_note` | FIXED |
| B-63 | data (R4.5 LOW) | API create: push landed but timed out → retry with same Idempotency-Key created « (2)» | `test_retry_after_push_that_landed_but_timed_out_does_not_duplicate` | FIXED |
| B-64 | test (R5 full run) | Settings e2e race: status text from the 1st save satisfied the 2nd wait | `test_token_field_is_empty_and_keeps_or_clears_token` | FIXED |
| B-65 | security (R5 VERIFY, HIGH) | `/admin/login/` (Django admin form) skipped the 2FA step → full session with password only | `test_admin_login_cannot_skip_the_2fa_step` | FIXED |
| B-66 | security (R5 VERIFY, MEDIUM) | Note render kept `javascript:`/`data:`/`vbscript:` in href/src (stored XSS from clipped pages) | `test_render_neutralises_dangerous_link_schemes[*]` | FIXED |
| B-67 | data (R5 VERIFY, MEDIUM) | A non-offline outbox failure blocked the whole queue; later editor saves silently «queued» | `test_failed_outbox_row_does_not_block_other_notes_and_save_reports_it` | FIXED |
| B-68 | data (R5 VERIFY, LOW) | Chain of offline saves on a conflicting base made one conflict copy per save | `test_chain_on_a_conflicting_save_updates_one_conflict_copy` | FIXED |
| B-69 | security (R5 VERIFY, LOW) | 2FA verify without row lock (parallel reuse of one code); per-account limit untested | `test_2fa_per_account_limit_blocks_even_the_right_code` | FIXED |
| B-70 | test (R5 final run) | Chat-error and task-status e2e interacted before page JS was bound (intermittent) | `test_chat_api_error_message_is_shown`, `test_rejected_status_change_is_reverted_and_reported` | FIXED |
| B-71 | data (owner run, Windows) | Vault cache with CRLF copies from an old autocrlf=true checkout + remote ahead → every pull failed «would be overwritten by checkout» (tasks, weekly, sync) | `test_pull_with_dirty_clone_and_remote_ahead` | FIXED |
| B-72 | logic (owner vault) | Weekly notes of the owner (`type: weekly_plan`, `week_number`, `date` = time of writing) were not recognised; template `ww`/`HH`/`mm` not filled | `test_b72_owner_weekly_plan_notes_use_week_number` | FIXED |
| B-73 | config (owner PC) | `OLLAMA_HOST` shared with the Ollama server held a bind address without scheme (`0.0.0.0`) → probe `MissingSchema`, Strictly Local always «PC offline» | `test_normalize_ollama_url` | FIXED |
| B-74 | deploy (server) | In the container LlamaIndex cached the embedding model under ~/.cache (/app, read-only for the app user) → `PermissionError` on re-index and AI chat | compose/Dockerfile `LLAMA_INDEX_CACHE_DIR` (verified on the server) | FIXED |
