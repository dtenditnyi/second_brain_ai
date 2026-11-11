# TEST PLAN — Second Brain AI

Run from `ai_manager/`: `../venv/Scripts/python.exe -m pytest` (all) · `-m "not e2e and not responsive"` (fast, ~5 s) · `-m e2e` · `-m responsive`.
Settings: `ai_manager/settings_test.py` (in-memory SQLite, logging to null). Browser: installed MS Edge via `--browser-channel msedge` (in `pytest.ini`).

## Isolation and mocks (`tests/conftest.py`)
| External thing | How it's handled |
|---|---|
| HuggingFace embedding model (downloaded at import of `core.rag_engine`) | module `llama_index.embeddings.huggingface` replaced by a `MockEmbedding(384)` before Django imports views |
| Ollama availability probe | `requests.get` in rag_engine raises `ConnectionError` by default; tests override `is_local_ai_ready` |
| Ollama / Gemini LLMs | `rag_engine.Ollama` / `GoogleGenAI` replaced by factories returning LlamaIndex `MockLLM` (echoes prompt → lets tests see the retrieved context) and recording kwargs |
| GitHub / GitPython | `git_sync.Repo` replaced by a class that raises if touched; tests inject fakes |
| Real vault / Chroma folders | `rag_engine.BASE_DIR` / `DB_DIR` redirected to `tmp_path` for every test |
| Chroma + LlamaIndex | **real** (temp dir) — retrieval, filtering and refresh are genuinely exercised |

Not mocked: Django, DB (SQLite), templates, URL routing, JSON parsing, markdown rendering, Chroma, LlamaIndex index/chat engine.

Known gap: production uses PostgreSQL; tests run on SQLite (NULL ordering in `order_by('due_date')`, strict varchar length are not exercised). Postgres-only behaviour is listed as a risk, not tested.

## Coverage matrix

| Area | File | What is checked | Level |
|---|---|---|---|
| Models | `test_models.py` | settings signal & defaults, no duplicate on resave, token encrypted at rest / decrypted on read / no double encryption / legacy plaintext, Task/ChatMessage defaults, ordering, `__str__`, cascade delete | unit |
| Auth | `test_auth.py` | login ok/invalid, `?next=` honoured and external `next` rejected, logged-in redirect, logout, register ok + settings + auto-login, invalid register (mismatch, weak, empty, duplicate) | integration |
| Access | `test_pages.py` | every private page & API → 302 login for anonymous; public pages 200; superuser-only link; admin pages/APIs denied for normal users | integration |
| Page smoke | `test_pages.py` | each page 200 with DEBUG on and off, title, sidebar/menu/viewport present, well-formed base layout | integration |
| Home | `test_pages.py` | per-user isolation, todo/progress/done split, top-focus tag, 3 most recent notes by mtime, 4 recent tasks, empty states, HTML escaping | integration |
| Chat page | `test_pages.py` | note list incl. subfolders, history order, last 50 limit, greeting shown/hidden, first-10 preselection (characterization of Q12) | integration |
| Notes page | `test_pages.py` | .md filtering, sync only when not cloned, no sync without repo | integration |
| Tasks page | `test_pages.py` | grouping, badges, isolation, completed limit 10 | integration |
| Settings page | `test_pages.py` | saved values reflected; PAT echoed (characterization Q7) | integration |
| Robustness | `test_pages.py` | pages work when the user's `UserSettings` row is missing | integration |
| APIs | `test_api.py` | sidebar stats; add task valid / invalid (no title, blank, bad date, bad priority, too long, bad JSON, GET); update task own / foreign 404 / GET / bad id / bad status; save settings full / clamp / strategy whitelist / partial / username rename (characterization Q6) / empty or taken username / null values / bad JSON; send message persist / legacy key / filter sanitising / empty / bad JSON; get note render + wiki links + aliases + tables + backlinks + subfolders + 400/404 + cross-user + traversal + attribute escaping; **CSRF enforced** and header accepted | integration |
| Core Matrix | `test_admin_matrix.py` | superuser-only page, all 4 tables, API forbidden for normal user (and redirect target exists), update each table, unknown table, missing row, delete each table, invalid table, GET, CSRF, stray text, empty temperature | integration |
| RAG engine | `test_rag_engine.py` | paths, Ollama probe (200/429/500/404/offline/timeout), cache reset per-user / for uncached user / all, no-repo notice, local-only offline, provider routing table (5 cases) incl. temperature & model, retrieved context injected, index built once & cached, provider switch, refresh picks up edits, selected-files filter, sync failure, exception text, bad temperature fallback, new engine per message (characterization Q2), no eager model load at import | unit/integration (real Chroma) |
| Git sync | `test_git_sync.py` | no URL, clone with token injection & parent creation, without token, stale dir removal, pull existing, error → False and token not logged | unit |
| E2E | `e2e/test_e2e_flows.py` | register → home; failed login message; each page without console/JS/HTTP errors and sidebar stats loaded; add task via modal → complete via checkbox → sidebar 100%; settings save + live theme + persisted accent; chat send (AI mocked); home search → chat auto-submit; context modal select/apply/Esc; notes open → wiki link → backlink; `?file=` deep link; logout; Core Matrix edit + drop; mobile menu open/close | E2E (Edge) |
| E2E errors / XSS | `e2e/test_e2e_errors.py` | settings/add-task/chat error messages shown, checkbox reverted on server error, AI reply / user text / note names / backlinks rendered as text | E2E |
| Responsive | `e2e/test_responsive.py` (71 tests) | 11 page states × 5 widths: no horizontal overflow, nothing sticking out of viewport, key elements visible inside viewport; mobile menu (360/390/768) and desktop sidebar; chat feed ≥ 60 % viewport height; admin table actions reachable; auth pages scroll on 360×480; translucent badges compiled | E2E |
| Screenshots | `e2e/test_screenshots.py` | only with `SCREENSHOT_DIR` set: PNG + metrics.json per page/width | tool |

## Characterization tests (`-m characterization`)
Pin current behaviour whose intent is unclear (see `docs/audit/QUESTIONS.md`): PAT echoed in settings HTML (Q7), display name renames username (Q6), new chat engine per message (Q2), first-10 notes preselected (Q12).

## Phase-2 baseline
`docs/audit/test-run-phase2.txt`: **177 tests, 142 passed, 35 failed**. All 35 failures are real defects (input for phase 3, see `docs/BUGS.md`); none were adjusted to pass.

## Final state
After phases 3–4: **275 passed, 1 skipped** (the skipped one is the screenshot tool). See `docs/audit/test-run-final.txt`.
Two rounds of mutation testing by an independent agent: 9 + 5 mutations, final round 5/5 detected.
