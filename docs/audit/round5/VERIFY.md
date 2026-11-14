# Round 5 — independent verification (security / data)

Scope: `git diff 6b595b4..HEAD` (feature/round5). Only findings are listed below. Areas with no finding:
vault paths and symlinks (`safe_path`, `_walk_md`), attachments, the SW not caching writes, redirects or errors,
Dataview (no eval, read-only), `/api/v1/` token-only (session cookies are ignored), and the `_landed_file` create.

## Findings

- **HIGH** `ai_manager/ai_manager/urls.py:7` — `/admin/login/` (Django admin) accepts the password alone and creates a
  full site session for a staff/superuser with 2FA on. Confirmed with the test client: after the admin login, `/settings/` returns 200
  without the TOTP step. The admin login has to require 2FA (or `/admin/` must be removed or blocked).
- **MEDIUM** `ai_manager/core/render.py:237` — python-markdown output is not URL-sanitised: `[x](javascript:alert(1))`,
  `[q][ref]` with `[ref]: javascript:…`, and `![a](javascript:…)` are rendered as live `href`/`src` (checked). There is no CSP. A clipped
  web page (bot capture / API create) or a pulled note gives stored XSS in the owner's session when the link is clicked.
- **MEDIUM** `ai_manager/core/notes_service.py:226-236` with `:202-206` — `flush_outbox` re-raises any non-offline error
  (VaultError permission/locked/conflict, NoteError e.g. "too many conflict copies"). The poison row stays first in the queue, and every
  later row (all notes) never flushes. Every new editor save of that note is then queued silently
  (`queued: True`, "waiting for earlier offline saves") instead of returning an error.
- **LOW** `ai_manager/core/api_v1.py:744-758` (capture_text) and `notes_append` (`:587`) — only create writes the
  `SB-Request` trailer and checks `_landed_file`. If a push reached GitHub but timed out, the retry of a bot capture/append
  with the same Idempotency-Key appends the text a second time.
- **LOW** `ai_manager/core/notes_service.py:226-231` — a chain of offline saves whose head conflicts makes one
  conflict copy for every queued save (each later base is the sha of the previous queued text). No loss, but N copies.
  A concurrent flush (scheduler + request) that reads a stale row list can also add a spurious copy.
- **LOW** `ai_manager/core/twofa.py:183-196` — `verify` reads and updates `totp_last_step` / backup codes without
  `select_for_update`. Two parallel second-step POSTs with the same TOTP or backup code can both succeed (replay/single-use race).
- **LOW** `ai_manager/core/views/auth.py:102` — the per-account 2FA limit (`TWOFA_USER_FAILS`, 10 per 15 min, across
  sessions) is untested: mutation `blocked = False` passes all round-5 tests. The cache counter is not atomic (get+set).
- **LOW** `ai_manager/static/js/pwa.js:12,41-46` — the offline capture queue (`sb-capture-queue:<uid>`, plain text in
  localStorage) is not cleared on logout. The next person on the device can read the previous user's unsent captures
  (`clearOfflineCaches` clears only CacheStorage; `Clear-Site-Data: "cache"` does not touch localStorage).
- **LOW** `ai_manager/static/js/sw.js:95` — caches are cleared only by logout or the login page. If the session expires and the
  next person uses the device offline (without visiting /login/ online), the cached `/`, `/notes/`, `/weekly/` and
  recent `/api/get-note/` responses of the previous user are served.
- **LOW** `ai_manager/core/dataview.py:388` + `render.py:271` — the 2 s deadline applies to each block. A note with hundreds of
  dataview blocks (or embeds of such notes) ties up a worker for minutes. The deadline is not checked during sort or table eval.

## Mutations (code restored, `git diff --stat` clean except this file)

1. `twofa.check_totp` `>` → `>=` (TOTP replay): caught (`test_totp_replay_and_backup_code_single_use`).
2. `login_2fa_view` `blocked = False` (per-account brute-force limit): **not caught**.
3. `_walk_md` follows symlinks: caught (`test_rag_loader_and_get_note_skip_symlinks`).
4. attachments serve `.md`: caught (`test_attachments_served_from_cache_with_safe_headers`).
5. `_landed_file` → `None`: caught (`test_retry_after_push_that_landed_but_timed_out_does_not_duplicate`).

Result: **4/5 caught**.

## Re-check of HIGH (2FA via admin login)

Verdict: **closed**. Throwaway probes (Django test Client, staff+superuser with TOTP on, GET and POST with password):
- `/admin/login/`, `/admin/login`, `/admin/LOGIN/`, `/admin//login/`, `/admin/./login/`, `/admin/login/x/`, `/admin/password_change/`, `/admin/password_reset/` all end in a redirect to `/login/` (unknown admin paths go through admin's catch-all → `admin:login` → the new redirect); no session gets `_auth_user_id`.
- `/login/` and `/LOGIN/` with the right password stop at `/login/2fa/`; `/login/2fa/` without a pending step goes back to `/login/`.
- No `django.contrib.auth.urls`/password reset/change views are mounted outside the admin; `login()` is called only in `core/views/auth.py:26` (register, new account only), `:54` (no 2FA) and `:106` (after the code). `/api/v1/` ignores session cookies (token-only, `core/api_v1.py:11`), tokens can only be created from a signed-in session.
- `next`: `//evil.com`, `https://evil.com`, `\evil.com`, ` //evil.com`, `%2F%2Fevil.com`, `///evil.com` → `/admin/`; `/\evil.com`, `/\t/evil.com`, `/\/evil.com` pass the new filter but the final redirect after 2FA (`_safe_next`, `url_has_allowed_host_and_scheme`) sends to `/`; encoded `/%2F%2Fevil.com` stays a same-site path. The admin redirect itself always points to the fixed `/login/`.
- New findings: none above INFO. INFO: `ai_manager/ai_manager/urls.py:14` lets `/\…` and control chars into `next` (harmless, blocked downstream); `url_has_allowed_host_and_scheme` there would make it self-contained.
- INFO applied: `url_has_allowed_host_and_scheme` added to the admin-login redirect.
