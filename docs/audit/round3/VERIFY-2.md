# Round 3 — Independent verification, round 2 (VERIFY-2)

Verifier: separate agent, fresh context, `feature/round3` @ 21cb9f4. No Docker / external APIs; local temp repos, scratch tests and Windows junctions in its own temp dir.
Suites: fast 467 passed; `test_round3.py` + `test_e2e_round3.py` 86 passed.

## Status of VERIFY-1 findings
| # | Fixed? | Evidence |
|---|---|---|
| D1 restore across versions | yes (design, not run live) | `DROP SCHEMA public CASCADE; CREATE SCHEMA public` + `psql --single-transaction -v ON_ERROR_STOP=1`; pg_dump never emits `CREATE SCHEMA public`. N6 caught (grep test only) |
| D2 duplicate 🆔 | yes | line identity on read + `ensure_ids` repair; full revert fails `test_b34_duplicate_id…`; offline test misses the cache-side revert (R4) |
| D3 tags / `[[#H]]` | yes | N7, N10 caught |
| D4 safe_path | yes | casefold, trailing dot/space, reserved names, `:`, control chars; junction `lnk → .git` rejected by resolved-parts check (scratch). `:`/trailing dots rejection acceptable (Obsidian forbids `:`) |
| D5 external images | yes | hook + link (N4 caught); marked percent-encodes `\`, tab, space |
| D6 .dockerignore | yes | `**/` patterns; nothing imports tests at runtime |
| D7 scheduler torch | yes | `core/paths.py`; no `rag_engine` import even lazily; `--loop` one process |
| D8 update.sh | yes via `.deployed_commit` | ERR trap never fires on build failure (R3) |
| D9 parser edges | mostly | fences, frontmatter comment, protected branch, sub-task deletion (N5, N8, N9, N11 caught); R2 regression, R5 gap |
| D10 WEB_BIND doc | yes | |
| D11 image hardening | yes / partial | root-owned code, writable volumes, tests excluded; cloudflared configurable, default `latest` |
| M1 / M8 / M11 | caught | `test_m1_…`, `test_m8_…`, `test_m11_…` |

## New mutation checks
| # | Mutation | Result |
|---|---|---|
| N1 | casefold dropped in first loop only | survived (resolved-parts layer catches; fine) |
| N15 | casefold dropped in both places | caught (5 tests) |
| N2 / N16 / N2+N16 | cache-side duplicate fix reverted | **survived** — test gap (R4) |
| N2+N16+N3 | + sync-time repair removed | caught |
| N3 | sync-time repair alone removed | survived (line identity keeps edits correct) |
| N4 | image hook not installed | caught (e2e b40) |
| N5 | delete only parent line | caught |
| N6 | restore without `--single-transaction` | caught |
| N7 | old tag regex | caught |
| N8 | frontmatter skipping off | caught |
| N9 | fence closes regardless of length | caught |
| N10 | validate all tags on update | caught |
| N11 | protected branch → conflict | caught |
| N12 | trailing dot/space check removed | caught |
| N13 | resolved-parts `.git` re-check removed | **survived** — junction/symlink to `.git` untested |
| N14 | `close_old_connections()` removed | survived (hard to test; low) |

## Regressions / new defects
1. **R1 Medium (regression of B-34):** read-only token + duplicate IDs → `_write(ensure_ids)` raises `TaskSyncError(PERMISSION_HINT)`, sync returns `error`, `_cache_from_note` never runs → empty task list, push attempted every minute. Fix: catch `TaskSyncError`, fall through to the cache rebuild.
2. **R2 Medium/Low (regression of B-41):** a note starting with `---` without a closing line loses every task (`parse("---\n## In\n- [ ] a 🆔 aaaaaa\n") == []`); updates `TaskNotFound`; `add` writes into the "frontmatter" invisibly; cache rebuild deletes rows. Fix: frontmatter only when a closing `---`/`...` exists.
3. **R3 Low:** B-39 ERR trap dead — `compose` is a shell function, without `set -E` the trap does not fire. Fix `set -Eeuo pipefail`.
4. **R4 Low test gaps:** `test_b34_duplicates_are_kept_apart…` syncs once (passes with the cache fix reverted) → sync twice + assert unique non-empty IDs; no test for symlink/junction to `.git` (N13); no test for the sync-time repair alone (N3).
5. **R5 Low:** deleting a parent leaves sub-tasks after a blank line (orphaned indented block).

Verdict: **NOT PASSED (narrowly)** — all VERIFY-1 defects fixed (incl. both Highs), M1/M8/M11 caught; R1, R2 must be fixed with tests; R3, R4 small follow-ups.

## Follow-up (main agent, after this report)
R1–R5 and the test gaps were fixed with regression tests in the next commit (BUGS B-44…B-48); the mutations N2+N16, N3 and N13 were re-run by the main agent and are now caught — see `docs/audit/LOG.md` (2026-11-11 "verification 2 follow-up"). Per the spec (0.5.7, at most 2 verifier rounds) no third round was started; the Round 4 verifier re-checks the shared modules.
