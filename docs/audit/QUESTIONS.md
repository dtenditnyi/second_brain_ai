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
