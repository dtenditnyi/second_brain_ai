# SITE MAP — Second Brain AI

Snapshot of `main` @ 6a1d8ee (analysed on branch `feature/audit`). Status legend:
**OK** works · **BROKEN** demonstrably wrong · **PARTIAL** works with defects · **UNCLEAR** purpose not clear from code/history (kept as-is, pinned by a characterization test, question in `docs/audit/QUESTIONS.md`).
Bug ids (B-xx) refer to `docs/BUGS.md`.

## 1. Stack (verified in code)

| Item | Fact |
|---|---|
| Framework | Django 6.1 (`requirements.txt`), single app `core`, project `ai_manager/ai_manager` |
| DB | PostgreSQL 16 via docker-compose (`settings.DATABASES` → `django.db.backends.postgresql`, host `db`). Legacy `db.sqlite3` (Aug 2026, pre-migration, up to core 0005) still in the folder. Migration commit: 837ed93 |
| HTMX | **Not used.** No `htmx` anywhere on `main`; a remote branch `origin/feature/htmx-migration` exists but is not merged. Frontend = server-rendered templates + vanilla JS `fetch()` to JSON endpoints |
| CSS | Tailwind v4 CLI: `static/css/input.css` → compiled `static/css/styles.css` (committed). Theme tokens via CSS variables + `data-theme` / `data-accent` on `<html>` |
| Static | WhiteNoise (`CompressedStaticFilesStorage`, manifest disabled) |
| Prod server | gunicorn (3 workers, timeout 300) + Cloudflare tunnel (docker-compose `tunnel`, `run_matrix.bat` for Windows) |
| AI | `core/rag_engine.py`: LlamaIndex + ChromaDB (`chroma_db/`), embeddings HuggingFace `BAAI/bge-small-en-v1.5` (loaded at import), LLM Ollama `llama3:latest` at `OLLAMA_HOST` (default `http://192.168.1.128:11434`) or Google Gemini `gemini-3.6-flash` (`GEMINI_API_KEY`) |
| Vault | `core/git_sync.py` (GitPython) clones/pulls a user's GitHub repo into `obsidian_data/user_<id>/` |
| Auth | Django sessions; `UserCreationForm` / `AuthenticationForm`; superuser flag gates the custom admin console |

## 2. URLs / pages

| URL | Name | View | Template / JS | Access | What it shows / does | Status |
|---|---|---|---|---|---|---|
| `/admin/` | — | Django admin | built-in | staff | Django admin. **No models registered** (`core/admin.py` empty) → only Users/Groups | OK |
| `/login/` | login | `auth.login_view` | `registration/login.html` (standalone, no base) | public; logged-in → redirect home | Username/password form, generic error message | PARTIAL: ignores `?next=` (always → home) B-12 |
| `/logout/` | logout | `auth.logout_view` | — | any | Logs out (GET), redirect `/login/` | OK (GET logout = CSRF-able, minor) |
| `/register/` | register | `auth.register_view` | `registration/register.html` | public; logged-in → home | `UserCreationForm` (username, password1, password2), logs in, → home; post_save signal creates `UserSettings` | PARTIAL: field errors not shown, only generic msg (minor) |
| `/` | home | `pages.home_view` | `home.html` + `tasks.js`, `home.js` | login | Dashboard: greeting (display_name), search box (→ chat via sessionStorage), Recent Tasks (4, with checkboxes), Recent Notes (3 by mtime), "AI Analytics" (pending count, notes count, top tag), "Generate Status Report" (calls chat API), Kanban board todo/in-progress/done | OK (see B-06 report = real LLM call) |
| `/chat/` | chat | `pages.ai_chat_view` | `ai-chat.html` + `chat.js` | login | Context panel (first 10 notes pre-selected), "+ Add Documents" modal (checkbox per note, Select All, Apply), chat feed (last 50 messages), composer (Enter sends, Shift+Enter newline) | PARTIAL: greeting bubble never shows (B-05); replies inserted as raw HTML (B-09) |
| `/notes/` | notes | `pages.notes_view` | `notes.html` + `notes.js` | login | On first visit clones the vault if URL configured and no `.git`; 3 panes: file explorer, rendered note, backlinks. `?file=<name>` auto-opens a note | OK (sync is blocking on first visit) |
| `/tasks/` | tasks | `pages.tasks_view` | `tasks.html` + `tasks.js` | login | Active tasks (not done, ordered by due date) with priority/date/tags; Completed (last 10); "+ Add New Task" modal | OK |
| `/settings/` | settings | `pages.settings_view` | `settings.html` + `settings.js` | login | Profile (Display Name bound to **username**!, email), theme, accent, GitHub URL + PAT (PAT rendered into page HTML), AI strategy, temperature; JS appends "Save System Configuration" button | PARTIAL: B-03 empty/duplicate username, B-13 PAT echoed |
| `/system-matrix/` | admin_dashboard | `admin.admin_dashboard_view` | `admin_dashboard.html` (standalone) + `admin.js` | superuser (else → `/login/`) | "Core Matrix": tabs Users / Settings / Tasks / Chat log (last 100); inline edit (Commit) and delete (Drop) per row; "Back to Dashboard" link | PARTIAL: "Back to Dashboard" goes to `/notes/` (UNCLEAR, Q4); no mobile layout |

### JSON API

All mutating endpoints are `@csrf_exempt` (B-01). Bodies are JSON (`application/json`).

| URL | Name | Method | Access | Input | Effect / output | Status |
|---|---|---|---|---|---|---|
| `/api/send-message/` | api_send_message | POST | login (anon → 302 login) | `{message, selected_files \| selectedFiles}` | Saves user msg, calls `rag_engine.ask_second_brain`, saves AI msg, `{status, reply}`; empty message → 400 | PARTIAL: invalid JSON → 500 (B-02) |
| `/api/save-settings/` | api_save_settings | POST | login | `{username, display_name, email, theme, accent_color, ai_strategy, temperature, github_repo_url, github_token}` | Updates `User.username/email` and `UserSettings`; clamps temperature 0..1; validates ai_strategy; resets RAG cache | BROKEN on edge cases: empty username saved (B-03), duplicate username → 500 (B-03), `null` url/token → 500, invalid JSON → 500 |
| `/api/get-note/` | api_get_note | GET `?name=` | login | note name w/o `.md` | Finds file anywhere in user vault, renders Markdown (+fenced_code, tables), converts `[[wiki|alias]]` links, lists backlinks with 40-char snippets | OK (raw HTML of notes is passed through; own content) |
| `/api/sidebar-stats/` | api_sidebar_stats | GET | login | — | `{percent, done, total}` for sidebar "Neural Sync" bar | OK |
| `/api/add-task/` | api_add_task | POST | login | `{title, priority, due_date, tags}` | Creates Task for current user | BROKEN on bad input: missing title / bad date → 500 (B-04); any priority string accepted |
| `/api/update-task/` | api_update_task | POST | login, owner only (other's task → 404) | `{task_id, status}` | Sets status | BROKEN: GET → 500 "didn't return HttpResponse" (B-04); any status string saved; non-numeric id → 500 |
| `/api/admin/update-row/` | api_admin_update | POST | superuser; others → 302 to non-existent `/accounts/login/` (B-11) | `{table: users\|settings\|tasks\|messages, id, fields}` | Updates fields of that row | PARTIAL: errors → 500 with exception text |
| `/api/admin/delete-row/` | api_admin_delete | POST | superuser (same B-11) | `{table, id}` | Deletes row (deleting a `settings` row breaks that user's pages, B-07) | PARTIAL |

## 3. Forms and buttons

| Where | Element | Does | Data changed |
|---|---|---|---|
| login | form POST | authenticate + session | session |
| register | form POST | create user (+ UserSettings via signal), login | `auth_user`, `core_usersettings` |
| sidebar (all base pages) | nav links, Log Out, Core Matrix (superuser only), "Neural Sync" bar (fetch `/api/sidebar-stats/`), mobile ☰ / × | navigation | — |
| home | search input (Enter) | stores query in `sessionStorage.pending_ai_query`, goes to `/chat/`, chat auto-submits it | ChatMessage ×2 |
| home | Recent Tasks checkbox | `/api/update-task/` done/todo, reload | Task.status |
| home | Generate Status Report | `/api/send-message/` with fixed prompt; reply shown in card | ChatMessage ×2 (prompt is stored in chat history — UNCLEAR whether intended, Q3) |
| home | Kanban cards | display only (cursor-pointer but no handler) | — |
| chat | + Add Documents / modal checkboxes / Select All / Apply / × / backdrop / Esc | choose notes used as retrieval filter (client state only) | — |
| chat | composer (Enter / ➤) | `/api/send-message/` | ChatMessage ×2 |
| chat | context list items | link to `/notes/?file=<name>` | — |
| notes | file item / wiki link / backlink card | `/api/get-note/` and render | — |
| tasks | + Add New Task → modal form (title required, priority, date, tags) → Save / Cancel | `/api/add-task/` then reload | Task |
| tasks | checkbox | `/api/update-task/` (checked → done, unchecked → todo; an in_progress task becomes done/todo) | Task.status |
| settings | theme select / accent radios | live preview only | — |
| settings | Save System Configuration (created by JS) | `/api/save-settings/` | User.username, User.email, UserSettings.* |
| system-matrix | tab buttons | switch visible table | — |
| system-matrix | Commit | `/api/admin/update-row/` | any row of 4 tables |
| system-matrix | Drop (confirm) | `/api/admin/delete-row/` | deletes row (cascade for users) |

## 4. Models (`core/models.py`)

| Model | Fields | Notes |
|---|---|---|
| `UserSettings` | user (1:1 User, `related_name='settings'`), display_name, theme (default cyberpunk), accent_color (cyan), ai_strategy (auto/local_only/cloud_only), temperature (0.7), github_repo_url (URLField 500), github_token (`EncryptedCharField` 255) | Created by `post_save(User)` signal. `user.settings` is accessed without a fallback everywhere (B-07) |
| `EncryptedCharField` | Fernet key = first 32 bytes of SECRET_KEY, padded with `0` | Decrypt failure returns the raw value (legacy plaintext allowed). Values starting with `gAAAAAB` are stored as-is. Long tokens may exceed 255 chars after encryption (B-14). Changing SECRET_KEY makes tokens unreadable (returned as ciphertext) |
| `Task` | user FK, title (255), status (todo/in_progress/done), priority (low/medium/high/urgent), due_date, tags (comma-separated string, 100), created_at | choices are not enforced by API (B-04) |
| `ChatMessage` | user FK, role (`user`/`ai`, free text 10), content, created_at; ordering created_at | |

Migrations 0001–0006, no data migrations.

## 5. Background work / integrations

- No Celery/cron. All work is synchronous inside requests:
  - `notes_view` → `git_sync.sync_obsidian_repo` (first visit only).
  - `ask_second_brain` → on first message per process: git clone/pull, build or refresh Chroma index (embedding all notes), choose LLM; then `engine.chat()`. Cached per user in process memory (`_user_chat_engines`, `_user_indexes`), so with 3 gunicorn workers each worker keeps its own cache.
- `is_local_ai_ready()` probes `OLLAMA_HOST/api/tags` (3 s timeout) on **every** message.
- Strategy: `local_only` + offline → error text; `auto` → Ollama if online else Gemini; `cloud_only` → Gemini.
- A new chat engine is built for every message, so conversational memory between turns is not kept (only retrieval context) — UNCLEAR whether intended (Q2).
- `Settings.llm` / `Settings.embed_model` are process-global LlamaIndex settings shared by all users (B-10).
- `reset_chat_engine(user_id)` clears **all users'** caches when that user has no cached engine (B-08).
- Embedding model is downloaded/loaded at import of `core.rag_engine` (every process start; `manage.py check` takes ~30 s; needs network on first run) (B-15).

## 6. Authorization summary

| Area | Rule | Status |
|---|---|---|
| pages | `@login_required(login_url='login')` | OK |
| user data | all queries filtered by `request.user` (tasks, messages, vault folder `user_<id>`) | OK — cross-user update returns 404 |
| custom admin | `user_passes_test(is_superuser)` | OK, but APIs redirect to `/accounts/login/` (404) instead of 403 (B-11) |
| CSRF | All JSON POST endpoints `@csrf_exempt` (incl. admin delete-row) | BROKEN security (B-01) |
| DEBUG | hard-coded `DEBUG = True` (env var commented out) also in production | security finding (Q1) |

## 7. Unused / odd code (kept, marked)

- `core/views/api.py`: `import rag_engine` used; `views/pages.py` imports `rag_engine` at module level but uses local imports — harmless.
- `base.html` duplicates `layout.js` mobile-menu logic inline (two click handlers on the same buttons) — harmless duplicate.
- `get_user_config()` anonymous branch is unreachable (all callers are `login_required`).
- `app_config.json` (repo root of ai_manager) is not read by any code — UNCLEAR (Q5).
- `cloudflared.exe` (55 MB) is committed to git.
- `tasks.js` checkbox handler: only a network exception reverts the checkbox; HTTP errors are silently ignored.
