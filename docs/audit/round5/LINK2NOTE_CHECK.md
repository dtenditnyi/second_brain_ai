# Live check: site ↔ Link2Note bot (2026-11-12)

- Setup: `runserver --settings=ai_manager.settings_local` (copy DB `audit_copy_db.sqlite3`) on 127.0.0.1:8791; throwaway user `l2n_contract`
  with a **local temp bare repo** (PARA fixture + «Входящие», tasks note, weekly note, `03 - Resources/📥 Из ссылок`); token per DEPLOY.md §12
  (write: bot folder, «Входящие», tasks note; delete: bot folder; read + ai). The real user and their GitHub settings were not touched.
- Bot: `../Link2Note/Link2Note`, `uv sync`, `uv run python scripts/check_second_brain_api.py --all` → **18 passed, 0 failed**
  (health, 401, create, Idempotency replay without duplicate, idempotency_mismatch, lookup with url normalisation, PATCH frontmatter,
  list `fm.status`, PUT, 409 on stale `if_sha`, 422 bad tag, 403 outside write_paths, `fun` tag, DELETE, 404, tasks, capture, ask).
- Git history of the test repo: one commit per operation (`api: create/frontmatter/edit/delete`, `tasks: add`, `api: capture`), the
  replayed create produced no second commit, the bot's test folder was fully cleaned by the script, unrelated note `02 - Areas/Личное.md`
  unchanged; «Входящие» got one line before the `🔗` line. The task sync added `🆔` to two ID-less tasks of the tasks note — Round 3 design.
- `/ask` answered within the contract format (no Gemini key in this shell's environment is required for the ✅).
- Docker: daemon not running on this PC → the prod-image `/healthz/` and the bot container `api-health` step were **not** run (owner step, SUMMARY).
- Clean-up: server stopped, user + token deleted from the copy DB, its clone `obsidian_data/user_4` and the temp repo removed.
- Bot bugs found: none. Note: port 8765 is used by Anki (AnkiConnect) on this PC — do not use it for the site.
