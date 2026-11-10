# RESPONSIVE — phase 4

Method: `tests/e2e/test_screenshots.py` (run with `SCREENSHOT_DIR=...`) seeds realistic data (long task titles, 14 notes with long names, a Markdown note with a table and code, chat history, admin) and captures 11 page states × 5 widths (360, 390, 768, 1024, 1440) into `responsive/before/` and `responsive/after/`, plus `metrics.json` (document scroll width, elements sticking out of the viewport, tap targets < 44 px, text < 12 px, horizontal scrollers).
Guard: `tests/e2e/test_responsive.py` (74 tests, marker `responsive`).

## Summary (metrics.json)

| | before | after |
|---|---|---|
| page states with horizontal overflow / clipped content | 8 of 55 | **0** |
| text nodes < 12 px | 63 | 15 (remaining: uppercase mono micro-labels on desktop only, by design) |
| tap targets < 44 px (all widths, incl. desktop & native checkboxes) | 653 | 450 (phone/tablet: inputs & buttons now ≥ 44 px; remaining are native checkboxes 24 px, inline text links, desktop-only controls) |

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
| R12 | **Regression from R1, found by the independent verifier**: the now-`fixed` chat context modal (and the task modal) were painted *under* the z-40 mobile top bar because `<main>` had `z-10` (own stacking context) → modal close button not clickable on phones/tablets | `ai-chat.html`, `tasks.html`, < 1024 | `z-10` on `<main>` only from `lg` | `test_modals_are_above_mobile_header[360,768]` |
| R13 | Chat at 1024 px: three columns left the conversation ~230 px wide | `ai-chat.html` | context column `lg:w-64 xl:w-80` | screenshot |
| R14 | Markdown tables had no cell padding/borders ("Column AColumn B") | notes | `.markdown-body th, td` padding + border | screenshot |
| R15 | Long unbroken words/URLs (task titles, chat) — guard added; no overflow at 360 px | home/tasks/chat | (already handled by layout) | `test_long_unbroken_words_do_not_overflow` |
| R11 | `#app-wrapper` used `w-screen` (100vw incl. scrollbar → potential 1-scrollbar overflow on desktop) | base.html | `w-full` | overflow tests |

Already fine before: `meta viewport` present on all pages; mobile off-canvas sidebar worked (`test_mobile_menu_opens_on_small_screens`); tasks/settings/home grids collapse to one column.

## Remaining / not changed
- Core Matrix tables below 1024 px scroll horizontally; Commit/Drop sit at the right end with no visual "scroll" hint, and text inputs inside cells are narrow (admin-only page; converting rows to cards would be a redesign).
- Native checkboxes are 24 px on phones (inside clickable rows/labels where available); enlarging further would change the look — left.
- The mobile sidebar has no backdrop and does not close on outside tap (menu still works via ×) — left as is (behaviour change).
- Uppercase mono micro-labels (`text-[10px]` in a few desktop-only places) kept for style.

---

# RESPONSIVE — Round 2

Method: same seeded data; `test_screenshots.py` now captures 11 page states × **11 sizes** (`responsive_helpers.SHOT_SIZES`: 320×568, 375×667, 390×844, 414×896, 768×1024, 834×1194, 1024×768, 1280×800, 1440×900, 1920×1080 and phone landscape 667×375) into `responsive/round2/before/` (templates as of f966afb) and `responsive/round2/after/`, each with `metrics.json`.
Guards: `tests/e2e/test_responsive.py` (overflow + key elements now at all 11 sizes) and `tests/e2e/test_responsive_round2.py` (tap zones, 16 px inputs, chat composer, modals, Core Matrix cards / scroll hint, focus ring, skip link, reduced motion, contrast, no theme flash); flows in `tests/e2e/test_e2e_round2.py` (mobile menu backdrop/Esc/scroll lock).

## Summary (metrics.json, 121 states)

| | before | after |
|---|---|---|
| states with horizontal overflow | 2 (login/register at 320 px) | **0** |
| tap targets < 44 px below 1024 px | 483 (old metric) | **0** (Round 2 metric, see note) |
| text nodes < 12 px (all sizes) | 33 | 16 (admin mono captions / `kbd` hints on desktop) |

Note on the tap-target metric: it now measures a checkbox/radio through its wrapping `<label>` (that is the real hit area, 44 × 44 via `.tap-zone`), ignores visually-hidden elements (skip link, `sr-only` labels) and links inside running text (WCAG 2.5.8 inline exception), and no longer counts `<label for>` captions of text fields (the field itself is the target). The before/after numbers therefore are not a 1:1 comparison; the after value is enforced by `test_tap_targets_at_least_44px_below_desktop[*]` (77 states).

## Issues found and fixes

| # | Problem (before) | Fix | Test |
|---|---|---|---|
| R16 | No single design system: one-off colours per page, `opacity-50/60` text (≈ 2.9:1 contrast), unreadable neon accents in the light theme, purple accent 3.9:1 on dark | `input.css`: tokens exposed with `@theme inline` (`text-fg/soft/muted`, `bg-accent/10`, `border-line`…), components in `@layer components` (`.btn/.btn-solid/.btn-ghost/.btn-danger`, `.field*`, `.badge-*`, `.alert-*`, `.modal-*`, `.empty-state`, `.spinner`, `.skeleton`, `.typing-dots`); `--text-muted` 5.9:1; purple `#C77DFF`; light-theme accents `#0E7490/#7E22CE/#15803D` | `test_text_tokens_meet_wcag_aa[*]` (2 themes × 3 accents) |
| R17 | Mobile menu: no backdrop, no outside-tap / Esc close, page scrolled behind it, closed off-canvas links still reachable with Tab | backdrop `#menu-backdrop`, Esc, close on link, `body.scroll-locked`, `inert` + `aria-hidden` when closed (< 1024 px), focus moves to × and back, `aria-expanded` | `test_mobile_menu_backdrop_escape_and_scroll_lock[*]`, `test_skip_link_and_menu_button_are_keyboard_reachable` |
| R18 | Core Matrix tables scrolled sideways on phones without any hint | below 768 px rows become cards (CSS only, `data-label` captions, actions as a full-width button row); from 768 px scroll shadows show there is more to the right | `test_core_matrix_tables_become_cards_on_phones[*]`, `test_core_matrix_scroll_hint_on_tablets[*]` |
| R19 | Checkboxes 24 px, small icon buttons, links, admin buttons < 44 px | `.tap-zone` labels (44 × 44), `.icon-btn` 44 px, `min-h-11` nav/links/admin buttons below `lg` | `test_tap_targets_at_least_44px_below_desktop[*]` |
| R20 | Chat on phones: page scrolled as a whole, composer could leave the screen (landscape), no safe areas, 15 px textarea (iOS zoom) | shell `h-dvh`, chat `main` not scrollable (only the feed), compact context bar < lg, section header and hint only from `lg`, composer with `env(safe-area-inset-bottom)`, `interactive-widget=resizes-content`, 16 px inputs below 1024 px / on touch | `test_chat_composer_stays_on_screen[667x375, 320x568, 390x844]`, `test_inputs_are_16px_on_phones[*]` |
| R21 | No `viewport-fit=cover` / safe-area handling (iPhone notch, landscape) | all layouts: `viewport-fit=cover`; mobile header `pt-safe`, sidebar/admin/auth padded with `env(safe-area-inset-*)`; modals padded by safe areas | screenshots 667×375 |
| R22 | Modals: chat modal `absolute` inside `main` on desktop, task modal opened via inline `onclick`, no Esc/backdrop for tasks, background scrolled | `.modal-overlay` (fixed, z 60, safe-area padding) + `.modal-panel`; Esc, backdrop click, focus to first field and back, scroll lock; `z-10` removed from `<main>` so desktop modals are above the sidebar | `test_modals_fit_small_screens[*]`, `test_modals_are_above_mobile_header[*]` |
| R23 | Login/register still overflowed at 320 px (decorative blobs) | blobs in a clipped fixed layer and 160 px below 400 px | overflow tests `login/register-320` |
| R24 | Loading / empty / error states inconsistent ("Processing logical cores…", "Defragmenting Vault Node Content", `alert()` in tasks) | typing indicator in chat, spinner in the Home report, skeleton in notes, `.empty-state` everywhere, inline `.alert` errors (task modal, settings, status toast), "System …" chat notices in amber | e2e `test_add_task_error_is_reported`, `test_rejected_status_change_is_reverted_and_reported` |
| R25 | No visible focus style; no skip link; notes list items not keyboard-operable (`<li>` click) | global `:focus-visible` ring, "Skip to content" link, note items and backlink cards are `<button>`s | `test_keyboard_focus_ring_is_visible`, `test_skip_link_…` |
| R26 | Motion ignored `prefers-reduced-motion`; theme could flash white before CSS | reduced-motion block (no transitions/animations, no smooth scroll); inline `html{background:…}` + `color-scheme`/`theme-color` meta per theme | `test_reduced_motion_disables_transitions`, `test_theme_background_painted_before_stylesheet[*]` |

Desktop: layout structure unchanged (sidebar + content, same grids); visible differences are the intended design-system colours/contrast, status selects on task cards, and the chat context panel showing the search scope instead of a pre-filled list.

## Independent verification (Round 2)
Round 1 (separate agent): `pytest -m responsive` 247 passed; 11-size overflow, mobile menu, cards on phones, focus ring, safe areas/dvh/16 px, empty/loading states, reduced motion and no theme flash all PASS. Findings, all fixed in 49ee379:

| # | Finding | Fix | Test |
|---|---|---|---|
| R27 | Light theme: the accent colour names in Settings (inline colours, 2.3–3.3:1) and tinted `.badge-accent` (3.9:1) failed AA; the token-only contrast test could not see it | `.swatch-*` classes with per-theme colours; lighter tint + darker text for badges in the light theme | **new** `test_rendered_text_contrast_meets_aa[*]` (5 pages × 2 themes × 3 accents, real rendered text against the composited background; a mutation that restores the old cyan label colour fails it with 2.41:1) |
| R28 | iPad landscape (1024 px, touch): status selects, report/add buttons, admin Commit/Drop/Disengage under 44 px; the tap test stopped at < 1024 | `@media (pointer: coarse)` → 44 px for buttons, fields, selects, admin controls | **new** `test_tap_targets_on_touch_tablet_landscape[*]` (has_touch) |
| R29 | Desktop regression: Notes explorer truncated "Daily note 2026-11-0…" → all names looked identical | two-line names + `title` | screenshot `notes_1440` |
| R30 | 667×375: chat feed only ≈ 110 px tall | slimmer mobile header on short screens, smart toggle on the same row | `test_chat_composer_stays_on_screen[667-375]` |

Left as is (reported by the verifier): Core Matrix keeps its own fixed dark "console" styling (it always rendered dark and does not use the light theme); it uses the shared tap-zone/touch rules and contrast was raised for its smallest label. From 768 px the wide tables still scroll sideways (scroll shadows show it), by design.
