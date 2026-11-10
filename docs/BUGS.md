# BUGS

Order: whole-site breakers → functional → security → minor. Each fix: red test → code → green → full suite green → commit.
Status: **FIXED** (commit) · **OPEN / not solved** (with analysis) · **QUESTION** (behaviour kept, see QUESTIONS.md).

| ID | Severity | Title | Test(s) | Status |
|---|---|---|---|---|
| B-15 | site | Embedding model downloaded/loaded at import → every process start slow, start fails offline / without HF access | `test_rag_engine::test_import_does_not_load_embedding_model_eagerly` | see below |
| B-07 | site | Any page → 500 when the user has no `UserSettings` row (e.g. after Core Matrix "Drop" on settings, or users created before the signal) | `test_pages::test_pages_work_for_user_without_settings_row[*]` | |
| B-10 | functional + privacy | LLM choice is process-global (`Settings.llm`); a user's chat may run on another user's provider (a *Strictly Local* user can be answered by Gemini, i.e. notes sent to the cloud) | `test_rag_engine::test_each_user_keeps_own_llm` | |
| B-04 | functional | Task APIs: missing/blank title, bad date, unknown priority/status, non-numeric id → 500 or invalid data; `GET /api/update-task/` → 500 ("didn't return an HttpResponse") | `test_api::test_add_task_invalid_payload_returns_400[*]`, `test_update_task_*` | |
| B-02 | functional | Malformed JSON body → 500 in all JSON POST APIs | `test_api::*malformed_json*` | |
| B-03 | functional | Save settings: empty username saved (user cannot log in any more), taken username → 500 (IntegrityError), `null` URL/token → 500 | `test_api::test_save_settings_empty_username_rejected`, `..._taken_...`, `..._null_values_...` | |
| B-05 | functional | Chat greeting never shown: `reversed(queryset)` is always truthy in `{% if not chat_history %}` | `test_pages::test_chat_greeting_shown_when_history_empty` | |
| B-08 | functional | `reset_chat_engine(uid)` wipes **all** users' caches when uid has no cached engine | `test_rag_engine::test_reset_chat_engine_for_uncached_user_keeps_other_users_cache` | |
| B-12 | functional | Login ignores `?next=` (always → home) | `test_auth::test_login_respects_next_parameter` | |
| B-11 | functional | Admin APIs redirect non-superusers to non-existent `/accounts/login/` (404) | `test_admin_matrix::test_admin_api_forbidden_for_normal_user[*]` | |
| B-17 | functional | Core Matrix: empty temperature → `float('')` → 500 | `test_admin_matrix::test_admin_update_settings_empty_temperature_is_not_500` | |
| B-18 | functional (UX) | JS ignores API errors: add-task modal silently stays, settings button stuck on "Saving Cores...", chat shows misleading "connection failed" | e2e `test_e2e_errors.py` | |
| B-01 | security | All state-changing JSON endpoints are `@csrf_exempt` (incl. admin delete/update and settings) → cross-site request forgery possible for logged-in users | `test_api::test_state_changing_api_requires_csrf_token[*]`, `..._accepts_csrf_header`, `test_admin_matrix::test_admin_delete_requires_csrf` | |
| B-09 | security | Chat/home render AI replies and user text with `innerHTML` (HTML/JS injection from LLM output or note content) | e2e `test_chat_reply_is_rendered_as_text` | |
| B-20 | security | Wiki-link target/alias inserted unescaped into `<a data-note="…">` attribute | `test_api::test_get_note_wikilink_target_is_attribute_escaped` | |
| B-16 | minor | Stray literal text "Anti-corruption layer code entry point" in each Core Matrix settings row | `test_admin_matrix::test_dashboard_has_no_stray_debug_text` | |
| B-19 | minor | `base.html`: `#app-wrapper` never closed, `</body>` before scripts | `test_pages::test_base_layout_html_is_well_formed` | |
| B-13 | security (design) | GitHub PAT rendered into settings page HTML | characterization `test_settings_page_echoes_github_token_into_html` | QUESTION Q7 |
| B-14 | latent | `EncryptedCharField(max_length=255)`: Fernet ciphertext of a token > ~140 chars exceeds 255 → DB error on Postgres | — | OPEN (needs migration, see below) |
| B-21 | security (design) | PAT stored in plain text in vault `.git/config` (token in remote URL) | — | QUESTION Q13 |
| B-06 | note | "Generate Status Report" stores its prompt/answer in chat history | — | QUESTION Q3 |

## Details

(filled in per bug below as fixes land)
