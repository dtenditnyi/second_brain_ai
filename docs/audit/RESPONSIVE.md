# RESPONSIVE — phase 4

Method: `tests/e2e/test_screenshots.py` (run with `SCREENSHOT_DIR=...`) seeds realistic data (long task titles, 14 notes with long names, a Markdown note with a table and code, chat history, admin) and captures 11 page states × 5 widths (360, 390, 768, 1024, 1440) into `responsive/before/` and `responsive/after/`, plus `metrics.json` (document scroll width, elements sticking out of the viewport, tap targets < 44 px, text < 12 px, horizontal scrollers).
Guard: `tests/e2e/test_responsive.py` (71 tests, marker `responsive`).

## Summary (metrics.json)

| | before | after |
|---|---|---|
| page states with horizontal overflow / clipped content | 8 of 55 | **0** |
| text nodes < 12 px | 63 | 15 (remaining: uppercase mono micro-labels on desktop only, by design) |
| tap targets < 44 px (all widths, incl. desktop & native checkboxes) | 653 | ~550 (phone/tablet: inputs & buttons now ≥ 44 px; remaining are native checkboxes 24 px inside clickable rows, inline text links, desktop-only controls) |

## Issues found and fixes

| # | Problem (before) | Where / widths | Fix | Test |
|---|---|---|---|---|
| R1 | **Chat unusable below 1024 px**: the chat section collapsed to 2 px height (context list took all space, `main` was `overflow-hidden` + `min-h-0`) | `ai-chat.html`, 360–768 | Mobile: `main` not height-locked, context list `max-h-48`, chat section `min-h-[75vh]`, aside `shrink-0`; desktop classes unchanged (`lg:`). Context modal `fixed` on mobile (stays `absolute` on desktop) | `test_chat_feed_is_usable[*]` |
| R2 | **Tailwind v4 ignores `bg-opacity-*` / `border-opacity-*` / `divide-opacity-*`** (102 uses): badges (URGENT/HIGH/ACTIVE/MEDIUM), active nav item, selected note, user chat bubbles rendered as **solid** colour → text invisible/low contrast | all pages, all widths | Converted to v4 syntax `bg-red-500/20`, `border-white/10`, … (templates + JS class lists; scripted, see D7) and rebuilt `styles.css` | `test_translucent_badges_are_not_solid` |
| R3 | Notes: 3-pane layout at 1024 px left ~80 px for the note text | `notes.html`, 1024 | Three columns only from `xl` (1280 px); below that panes stack | `test_no_horizontal_overflow_and_key_elements_visible[notes-1024]` |
| R4 | Core Matrix had no mobile layout: fixed 256 px sidebar, header overflowing at 360 px; tables clipped by `overflow-hidden` at 768/1024 px (Commit/Drop buttons cut off) | `admin_dashboard.html`, 360–1024 | Header wraps; sidebar becomes a horizontally scrollable tab bar below `md`; table wrappers `overflow-x-auto` with sensible `min-w` per table | `test_admin_table_actions_reachable[*]`, overflow tests |
| R5 | Login/Register: decorative 384 px blur blobs made the page 474 px wide on phones; `h-screen overflow-hidden` body could cut the card on short screens | `registration/*.html`, 360–390 | Body `min-h-screen overflow-x-hidden py-6`, `w-full` instead of `w-screen`, smaller blobs on phones, `pointer-events-none` | overflow tests, `test_auth_pages_scroll_on_short_screens[*]` |
| R6 | Register: password help text (`<ul>` inside `<p>`) rendered as large **black** text on dark background | `register.html`, all widths | Help text in a `div` with readable colour, 12 px, list bullets | screenshot |
| R7 | Tap targets < 44 px on phones: menu ☰ (40), menu ×, chat send (40), modal ×, inputs/buttons (38–42), task modal buttons | base/sidebar/chat/tasks | `p-2.5`, `w-11 h-11`, `py-3` on mobile; CSS `min-height: 44px` for `.input-field`/`.btn-primary` and 24 px radios/checkboxes **below 1024 px only** (desktop unchanged) | metrics |
| R8 | Home "Recent Tasks" checkbox shrank to 13 px next to long titles; chat modal checkboxes / close button squeezed | `home.html`, `ai-chat.html` | `shrink-0` | metrics |
| R9 | Rendered Markdown: wide tables/code stretched the reading pane; images unbounded | notes | `.markdown-body table, pre {overflow-x:auto}`, `img {max-width:100%}`, `overflow-wrap:anywhere` | overflow tests |
| R10 | 10 px labels (sidebar "Tasks completed", admin "Database Entities", register help) | various | `text-xs` (12 px) | metrics |
| R11 | `#app-wrapper` used `w-screen` (100vw incl. scrollbar → potential 1-scrollbar overflow on desktop) | base.html | `w-full` | overflow tests |

Already fine before: `meta viewport` present on all pages; mobile off-canvas sidebar worked (`test_mobile_menu_opens_on_small_screens`); tasks/settings/home grids collapse to one column.

## Remaining / not changed
- Native checkboxes are 24 px on phones (inside clickable rows/labels where available); enlarging further would change the look — left.
- The mobile sidebar has no backdrop and does not close on outside tap (menu still works via ×) — left as is (behaviour change).
- Uppercase mono micro-labels (`text-[10px]` in a few desktop-only places) kept for style.
