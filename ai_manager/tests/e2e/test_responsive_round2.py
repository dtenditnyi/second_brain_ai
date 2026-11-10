"""Round 2 responsive / visual checks.

* tap targets >= 44px on every page below 1024px (checkbox → its label hit zone);
* inputs >= 16px on phones (no iOS zoom);
* chat composer usable in phone landscape (667x375), feed scrolls, composer in view;
* Core Matrix: cards on phones, horizontal-scroll hint (scroll shadows) on tablets;
* modals fit small screens; visible keyboard focus ring; prefers-reduced-motion;
* WCAG AA text contrast in both themes; no theme flash (background painted inline).
"""
import pytest
from playwright.sync_api import expect

from core.models import UserSettings
from tests.e2e.responsive_helpers import PAGES, SHOT_SIZES, METRICS_JS
from tests.e2e.test_responsive import open_page, seeded  # noqa: F401 (fixture)

pytestmark = [pytest.mark.responsive, pytest.mark.e2e]

MOBILE_SIZES = [s for s in SHOT_SIZES if s[1] < 1024]


@pytest.mark.parametrize("size", MOBILE_SIZES, ids=[s[0] for s in MOBILE_SIZES])
@pytest.mark.parametrize("name", list(PAGES))
def test_tap_targets_at_least_44px_below_desktop(browser, live_server, seeded, name, size):
    _, width, height = size
    ctx, page = open_page(browser, live_server, name, width, height)
    try:
        m = page.evaluate(METRICS_JS)
        assert m["smallTargets"] == [], m["smallTargets"]
    finally:
        ctx.close()


@pytest.mark.parametrize("name,selector", [
    ("chat", "#chat-input"), ("settings", "#display-name"), ("tasks-modal", "#task-title"),
    ("login", "#id_username"), ("home", "#global-search-input"), ("system-matrix", "input[name=username]"),
])
def test_inputs_are_16px_on_phones(browser, live_server, seeded, name, selector):
    ctx, page = open_page(browser, live_server, name, 390, 844)
    try:
        size = page.locator(selector).first.evaluate("e => parseFloat(getComputedStyle(e).fontSize)")
        assert size >= 16, size
    finally:
        ctx.close()


@pytest.mark.parametrize("width,height", [(667, 375), (320, 568), (390, 844)])
def test_chat_composer_stays_on_screen(browser, live_server, seeded, width, height):
    ctx, page = open_page(browser, live_server, "chat", width, height)
    try:
        # The page itself does not scroll — only the feed does.
        container = page.evaluate("() => { const c = document.querySelector('.scroll-container'); return [c.scrollHeight, c.clientHeight]; }")
        assert container[0] <= container[1] + 1, container
        box = page.locator("#chat-input").bounding_box()
        assert box["y"] >= 0 and box["y"] + box["height"] <= height + 1, box
        feed = page.locator("#chat-feed").bounding_box()
        assert feed["height"] >= 100, feed
        # The feed starts scrolled to the newest message.
        at_bottom = page.evaluate("() => { const f = document.getElementById('chat-feed'); return f.scrollHeight - f.scrollTop - f.clientHeight < 4; }")
        assert at_bottom
    finally:
        ctx.close()


@pytest.mark.parametrize("width,height", [(320, 568), (667, 375), (390, 844)])
@pytest.mark.parametrize("name,panel,close", [
    ("chat-modal", "#context-modal .modal-panel", "#close-context-modal"),
    ("tasks-modal", "#task-modal .modal-panel", "#task-modal [data-close-task-modal]"),
])
def test_modals_fit_small_screens(browser, live_server, seeded, width, height, name, panel, close):
    ctx, page = open_page(browser, live_server, name, width, height)
    try:
        box = page.locator(panel).bounding_box()
        assert box["x"] >= 0 and box["y"] >= 0, box
        assert box["x"] + box["width"] <= width + 1 and box["y"] + box["height"] <= height + 1, box
        expect(page.locator("body")).to_have_class(__import__("re").compile("scroll-locked"))
        page.locator(close).first.click()
        expect(page.locator(panel)).to_be_hidden()
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [320, 375])
def test_core_matrix_tables_become_cards_on_phones(browser, live_server, seeded, width):
    ctx, page = open_page(browser, live_server, "system-matrix-tasks", width, 700)
    try:
        info = page.evaluate("""() => {
            const table = document.querySelector('#tasks-table table');
            const wrap = table.parentElement;
            const td = table.querySelector('tbody td[data-label]');
            return {display: getComputedStyle(td).display,
                    caption: getComputedStyle(td, '::before').content,
                    scrolls: wrap.scrollWidth > wrap.clientWidth + 1,
                    thead: table.querySelector('thead').getBoundingClientRect().height};
        }""")
        assert info["display"] == "block" and info["caption"].strip('"') == "ID", info
        assert not info["scrolls"] and info["thead"] <= 1, info
        btn = page.locator("#tasks-table .delete-row-btn").first
        btn.scroll_into_view_if_needed()
        expect(btn).to_be_in_viewport()
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [834, 1024])
def test_core_matrix_scroll_hint_on_tablets(browser, live_server, seeded, width):
    ctx, page = open_page(browser, live_server, "system-matrix-tasks", width, 1000)
    try:
        info = page.evaluate("""() => {
            const wrap = document.querySelector('#tasks-table table').parentElement;
            return {scrolls: wrap.scrollWidth > wrap.clientWidth + 1,
                    hint: wrap.classList.contains('scroll-shadows'),
                    bg: getComputedStyle(wrap).backgroundImage};
        }""")
        assert info["scrolls"] and info["hint"] and "radial-gradient" in info["bg"], info
    finally:
        ctx.close()


def test_keyboard_focus_ring_is_visible(browser, live_server, seeded):
    ctx, page = open_page(browser, live_server, "settings", 1280, 800)
    try:
        page.locator("#display-name").focus()
        page.keyboard.press("Tab")  # keyboard navigation → :focus-visible
        style = page.evaluate("() => { const s = getComputedStyle(document.activeElement); return [s.outlineStyle, s.outlineWidth, s.boxShadow]; }")
        assert style[0] != "none" or style[2] != "none", style
    finally:
        ctx.close()


def test_skip_link_and_menu_button_are_keyboard_reachable(browser, live_server, seeded):
    ctx, page = open_page(browser, live_server, "home", 390, 844)
    try:
        page.keyboard.press("Tab")
        assert page.evaluate("() => document.activeElement.textContent.trim()") == "Skip to content"
        page.keyboard.press("Tab")
        assert page.evaluate("() => document.activeElement.id") == "mobile-menu-open"
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        assert page.evaluate("() => document.activeElement.id") == "mobile-menu-close"
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)
        assert page.evaluate("() => document.activeElement.id") == "mobile-menu-open"
    finally:
        ctx.close()


def test_reduced_motion_disables_transitions(browser, live_server, seeded):
    ctx, page = open_page(browser, live_server, "home", 390, 844, reduced_motion="reduce")
    try:
        duration = page.locator("#main-sidebar").evaluate("e => getComputedStyle(e).transitionDuration")
        assert all(float(d.rstrip("ms")) < 0.01 or d.endswith("ms") and float(d[:-2]) < 1 for d in duration.split(",")), duration
    finally:
        ctx.close()


CONTRAST_JS = """
() => {
  const parse = c => { const m = c.match(/[\\d.]+/g).map(Number); return m.length >= 3 ? m : null; };
  const lum = ([r, g, b]) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b); };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const probe = document.createElement('span'); document.body.appendChild(probe);
  const colour = v => { probe.style.color = v; return parse(getComputedStyle(probe).color); };
  const bg = colour(getComputedStyle(document.documentElement).getPropertyValue('--bg-base'));
  const out = {};
  for (const token of ['--text-primary', '--text-secondary', '--text-muted', '--active-accent', '--danger', '--warning', '--success', '--info'])
    out[token] = ratio(colour(getComputedStyle(document.documentElement).getPropertyValue(token)), bg);
  probe.remove();
  return out;
}
"""


@pytest.mark.parametrize("theme", ["cyberpunk", "light"])
@pytest.mark.parametrize("accent", ["cyan", "purple", "green"])
def test_text_tokens_meet_wcag_aa(browser, live_server, seeded, theme, accent):
    UserSettings.objects.filter(user=seeded).update(theme=theme, accent_color=accent)
    ctx, page = open_page(browser, live_server, "home", 1280, 800)
    try:
        ratios = page.evaluate(CONTRAST_JS)
        low = {k: round(v, 2) for k, v in ratios.items() if v < 4.5}
        assert low == {}, low
    finally:
        ctx.close()


@pytest.mark.parametrize("theme,colour", [("light", "#F8FAFC"), ("cyberpunk", "#0D0D12")])
def test_theme_background_painted_before_stylesheet(browser, live_server, seeded, theme, colour):
    """No flash: the page background is inlined in <head>, before styles.css loads."""
    UserSettings.objects.filter(user=seeded).update(theme=theme)
    ctx, page = open_page(browser, live_server, "home", 1280, 800)
    try:
        inline = page.evaluate("() => document.head.querySelector('style').textContent")
        assert colour in inline
        assert page.evaluate("() => document.querySelector('meta[name=color-scheme]').content") == (
            "light" if theme == "light" else "dark")
    finally:
        ctx.close()
