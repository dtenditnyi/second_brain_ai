# Round 4 — independent verification (review of d82f0d0..c024485)

Scope: vault write safety, token rights, data loss, idempotency, prompt injection/XSS. Worktree review, no files changed except this one.
Baseline (round4+round5 acceptance, api_contract, agent_providers, vault_writer): 165 passed, 21 xfailed.

## HIGH
- [HIGH] core/api_v1.py:892 + core/agent.py:460 — `POST /api/v1/agent` checks only scope `ai`, but `run_agent` auto-applies additive changes (create/append/add_task) when `agent_auto_apply_additions` is on. That path skips `need_path`, so it ignores both the `write` scope and `write_paths`. Scenario: an ai-only token (or a prompt injection inside a note the agent reads) creates or appends notes anywhere in the vault. Fix: give `run_agent` an `auto_apply=False` argument from the API (or check `need_path("write", path)` for every auto-applied change).

## MEDIUM
- [MEDIUM] core/api_v1.py:911-912 — revert via the API checks only `need(token,"write")`. It does not check `write_paths`, and it does not check the `delete` scope or `delete_paths`, even though reverting a "create" deletes a note. Scenario: the bot token (write_paths = links folder) reverts a batch applied in the web UI that touched `01 - Projects/…`, which rewrites or deletes notes outside its rights. Fix: run `need_path("write", p)` for every applied change path, plus `need_path("delete", p)` for kind=create.
- [MEDIUM] core/agent.py:584 — `revert_batch` reverts and pushes each commit separately. If commit #2 hits a conflict, commit #1's revert is already pushed, but the status stays applied/partial. A retry reverts #1 a second time and gets a conflict, so the batch is stuck half-reverted. Fix: run all `git revert --no-commit` in one locked pass with a single commit and push, or drop each reverted sha from `batch.commits` as you go.
- [MEDIUM] core/frontmatter.py:90 — `render_value` writes strings unquoted. With `set={"title":"Ответ: да"}` the result is `title: Ответ: да`, which is invalid YAML, so Obsidian drops all properties. A value of `"#x"` becomes a comment, and `"[a"` or a list item containing ", " is mis-parsed. `fm.parse` still reads its own output back, so the API reports success. Fix: quote with `"…"` and escape when the value has `: `, ` #`, a leading special character (`[{>|*&!%@\`'"-?`), or `,` inside a list item.
- [MEDIUM] core/notes_service.py:382 — `_rename_plan` reads notes with `Path.read_text`, which translates universal newlines, then writes them back with `write_bytes`. Every CRLF note that links to the renamed note gets rewritten entirely in LF: a whole-file diff, plus Obsidian/mobile merge conflicts. This breaks the byte-exactness that B-49 fixed. Fix: use `read_bytes().decode("utf-8")` (also at line 131).
- [MEDIUM] core/notes_service.py:369 — the relink map uses `old.stem → new.stem`, so renaming `A/Note.md` also rewrites every `[[Note]]` that resolves to a different `C/Note.md` (same stem in another folder), which silently breaks those links. Links are matched case-sensitively, while Obsidian links are case-insensitive, so `[[note]]` is left broken. Fix: rewrite bare-stem links only when the stem is unique in the vault, and match case-insensitively.

## LOW
- [LOW] core/notes_service.py:195 + static/js/note_editor.js:216 — an offline save returns the old `base_sha`, and the editor keeps it. Two consecutive offline saves of one note then flush as: the first is written, the second conflicts (its base is stale) and becomes a "(конфликт …)" copy holding the user's newest text, while the note keeps the older one. Fix: chain queued saves (base = sha of the previous queued content) or coalesce rows per path.
- [LOW] core/notes_service.py:210 — `create_raw` raises `NoteError` when the conflict copy already exists (two conflicts for one note in the same minute). Nothing catches it, so the flush aborts and the outbox row blocks the queue. Fix: catch it and add a unique suffix.
- [LOW] core/notes_service.py:345 (web delete/rename) — no `base_sha` check, so deleting from the editor removes a note that was changed in Obsidian after it was opened (recoverable only from git history). Fix: accept an optional `base_sha` as `api_v1._delete_note` does.
- [LOW] core/api_v1.py:570 (`_nfc` on every path) — notes whose names are stored NFD in git (some iOS/isomorphic-git clients) are listed under their NFD path, but GET/PUT/DELETE on that path is normalised to NFC and returns 404. POST /notes can then create a duplicate NFC twin. Fix: when the NFC path is missing, fall back to the on-disk name.
- [LOW] core/api_v1.py:827-830 — `DELETE /tasks/{id}` needs `write` plus `write_paths`. The contract (§1 table) maps every DELETE to the `delete` scope and `delete_paths`. Fix: decide which applies and align either the code or the contract.
- [LOW] core/api_v1.py:399 — the unauthenticated `/health` exposes the global outbox count and the latest sync time across all users. Fix: without a token, return only status/version.
- [LOW] core/vault_writer.py vault_apply / contract §1 — when a push fails, the API returns 503 instead of queueing with `"pushed": false`. If a push actually reached the remote but the client timed out, a retry with the same key re-runs and POST /notes creates "name (2).md". Fix: document the behaviour, or look up an existing commit/path before re-creating.

## Checked, no finding
`safe_path` blocks `..`, `\`, drive letters, `:`/ADS, trailing dots and spaces, `.GIT`, Windows 8.3 `GIT~1` (verified), and symlink escape. `md_path` restricts writes to `.md`. Token auth is Bearer-only (no cookie). Batches and tasks are filtered by user. Idempotency compares requests by meaning, does not cache 5xx/429, and keys are scoped per token. JS diff/preview output is escaped.

## Mutations (5, all restored)
1. `agent.apply_batch`: base_sha check → `if False` — CAUGHT by tests/acceptance/test_round4.py::test_e3_conflict_on_apply
2. `api_v1._delete_note`: removed `need_path("delete")` — CAUGHT by tests/test_api_contract.py::test_lookup_read_list_patch_put_delete
3. `api_v1.within`: plain `startswith` (no segment boundary) — CAUGHT by tests/test_api_contract.py::test_create_validation[payload10-403]
4. `agent._wrap_note`: removed html escaping of path and text — CAUGHT by tests/acceptance/test_round4.py::test_e4_prompt_injection_in_note_is_data
5. `api_v1._idempotent`: skipped fingerprint comparison — CAUGHT by tests/test_api_contract.py::test_idempotency_same_request_by_meaning

Gaps in tests (no mutation spent): no test covers auto-apply via an API token, revert rights via the API, CRLF preservation on rename, or quoting of YAML frontmatter values.

## Fixes (main agent)
HIGH H1 → B-52; MEDIUM → B-53…B-57 (all with regression tests in `tests/test_round4_regressions.py`).
LOW: /health without token no longer shows global data (fixed). Left for Round 5 (REPORT R4.5): chained offline saves, duplicate conflict-copy name, web delete without base_sha, NFD paths, DELETE /tasks scope wording, push-reached-but-timeout duplicate.
