# Questions for the owner

Format: question · default chosen · where in code

1. **DEBUG is hard-coded `True`** (env read is commented out), also in Docker/production (compose sets `DEBUG=False` but it is ignored). Should production run with DEBUG off? · Default: left unchanged (changing it could break static serving you fixed in 149b45c/400a377) · `ai_manager/ai_manager/settings.py:83`
2. **Chat has no conversation memory**: a new chat engine is created for every message, so the LLM sees only retrieved notes, not previous turns. Intended? · Default: unchanged, pinned by test · `core/rag_engine.py:512-522`
3. **"Generate Status Report" on Home stores its fixed prompt and reply in chat history.** Intended? · Default: unchanged · `static/js/home.js`, `core/views/api.py:api_chat_message`
4. **"Back to Dashboard" in Core Matrix links to `/notes/`**, not `/` (home). Intended? · Default: unchanged · `templates/admin_dashboard.html:49`
5. **`ai_manager/app_config.json`** is not read by any code (contains a name and `alex@example.com`). Legacy? · Default: kept · `ai_manager/app_config.json`
6. **Settings "Display Name" field edits the login username** (`settings.js` sends `username = display_name`). Renaming your login when changing a display name — intended? · Default: kept behaviour, but empty or already-taken usernames are now rejected (B-03) · `static/js/settings.js:55`, `core/views/api.py:47`
7. **GitHub PAT is rendered back into the settings page HTML** (`value="{{ config.github_token }}"`), so it is visible in page source. Keep (convenient) or show blank/placeholder and keep existing token when field left empty? · Default: unchanged (changing needs a UX decision) · `templates/settings.html:83`
8. **Cloud model label mismatch**: settings dropdown says "Gemini 2.5 Flash", code uses `gemini-3.6-flash`. Which is right? · Default: unchanged · `templates/settings.html:93`, `core/rag_engine.py:149`
9. **Default `OLLAMA_HOST` is a LAN IP `192.168.1.128`.** Should it be configurable only via env? · Default: unchanged · `core/rag_engine.py:29`
10. **No UI to move a task to "In Progress"** (only Core Matrix can), although Home shows an "In Progress" column, and unchecking a done task sets it to `todo`. Add a control? · Default: unchanged (feature, not a bug) · `static/js/tasks.js`, `templates/home.html`
11. **Superuser can remove own superuser flag / delete own account in Core Matrix** (locks themself out). Add a guard? · Default: unchanged · `core/views/admin.py`
12. **Chat searches only the first 10 notes by default** (they are pre-checked; whole-vault search only when nothing is checked). With >10 notes, answers silently ignore the rest. Intended? · Default: unchanged, pinned by test · `core/views/pages.py:74`, `templates/ai-chat.html:115`, `static/js/chat.js:19`
13. **PAT stored in plain text in the vault's `.git/config`** (token embedded in remote URL). Use a credential helper / strip the token after pull? · Default: unchanged (needs design choice; tests document it) · `core/git_sync.py:28-40`
14. **First chat with a failed Git sync answers "Empty Response"** (LlamaIndex default for an empty index) instead of an explanatory message. Show "vault sync failed" instead? · Default: unchanged, pinned by test · `core/rag_engine.py` (index build branch)

## Round 2 — answered by the owner (docs/audit/PROMPT_ROUND2.md)
All 14 questions were answered and implemented in Round 2 — see `docs/audit/REPORT.md` → "Round 2", `docs/BUGS.md` (B-13, B-21, B-14, B-06, B-26…B-31) and `docs/audit/DECISIONS.md` (D9–D18).
