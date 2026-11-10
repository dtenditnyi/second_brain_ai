"""Responsive layout: every page at 360/390/768/1024/1440 px.

* no horizontal page overflow (document scrollWidth <= clientWidth) and no element
  sticking out of the viewport unless it sits inside a horizontal scroller;
* key elements visible; mobile menu works below 1024 px;
* page-specific regressions found in phase 4 (chat feed height, admin tables,
  auth pages scrollable, opacity utilities compiled).
"""
import pytest
from playwright.sync_api import expect

from tests.e2e.conftest import login
from tests.e2e.responsive_helpers import PAGES, WIDTHS, HEIGHT, seed, run_action, METRICS_JS

pytestmark = [pytest.mark.responsive, pytest.mark.e2e]

KEY = {
    "login": ["#id_username", "#id_password", "button[type=submit]"],
    "register": ["#id_username", "#id_password1", "button[type=submit]"],
    "home": ["#global-search-input", "#generate-report-btn"],
    "chat": ["#chat-input", "button[aria-label='Send message']", "#add-documents-button"],
    "chat-modal": ["#apply-context-button", "#close-context-modal", "#select-all-checkbox"],
    "notes": ["#workspace-content-area .markdown-body"],
    "tasks": ["header button.btn-primary"],
    "tasks-modal": ["#task-title", "#add-task-form button[type=submit]"],
    "settings": ["#display-name", "#theme-select", "#ai-temperature"],
    "system-matrix": [".tab-btn[data-tab='tasks-table']", "#users-table"],
    "system-matrix-tasks": ["#tasks-table"],
}


@pytest.fixture
def seeded(e2e_user, e2e_admin, isolated_vault):
    seed(e2e_user, isolated_vault)
    return e2e_user


def open_page(browser, live_server, name, width):
    path, role, action = PAGES[name]
    ctx = browser.new_context(viewport={"width": width, "height": HEIGHT[width]})
    page = ctx.new_page()
    if role:
        login(page, live_server, "e2e" if role == "user" else "e2eroot")
    page.goto(f"{live_server.url}{path}")
    page.wait_for_load_state("networkidle")
    if action:
        run_action(page, action)
    return ctx, page


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("name", list(PAGES))
def test_no_horizontal_overflow_and_key_elements_visible(browser, live_server, seeded, name, width):
    ctx, page = open_page(browser, live_server, name, width)
    try:
        m = page.evaluate(METRICS_JS)
        assert m["docScroll"] <= m["vw"], f"page scrolls horizontally: {m['docScroll']} > {m['vw']}"
        assert m["overflowing"] == [], m["overflowing"]
        for sel in KEY[name]:
            loc = page.locator(sel).first
            loc.scroll_into_view_if_needed()
            expect(loc).to_be_visible()
            box = loc.bounding_box()
            assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1, f"{sel} outside viewport: {box}"
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [360, 390, 768])
def test_mobile_menu_opens_on_small_screens(browser, live_server, seeded, width):
    ctx, page = open_page(browser, live_server, "home", width)
    try:
        sidebar = page.locator("#main-sidebar")
        assert sidebar.bounding_box()["x"] + sidebar.bounding_box()["width"] <= 0
        page.click("#mobile-menu-open")
        expect(page.get_by_role("link", name="Tasks")).to_be_in_viewport()
        page.get_by_role("link", name="Tasks").click()
        page.wait_for_url(f"{live_server.url}/tasks/")
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [1024, 1440])
def test_sidebar_always_visible_on_desktop(browser, live_server, seeded, width):
    ctx, page = open_page(browser, live_server, "home", width)
    try:
        expect(page.locator("#mobile-menu-open")).to_be_hidden()
        expect(page.get_by_role("link", name="Tasks")).to_be_in_viewport()
    finally:
        ctx.close()


@pytest.mark.parametrize("width", WIDTHS)
def test_chat_feed_is_usable(browser, live_server, seeded, width):
    """Before phase 4 the chat section collapsed to 2 px below 1024 px."""
    ctx, page = open_page(browser, live_server, "chat", width)
    try:
        section = page.locator("main > section").bounding_box()
        assert section["height"] >= 0.6 * HEIGHT[width], section
        page.locator("#chat-input").scroll_into_view_if_needed()
        expect(page.locator("#chat-input")).to_be_in_viewport()
    finally:
        ctx.close()


@pytest.mark.parametrize("width", [360, 768, 1024])
def test_admin_table_actions_reachable(browser, live_server, seeded, width):
    ctx, page = open_page(browser, live_server, "system-matrix-tasks", width)
    try:
        btn = page.locator("#tasks-table .delete-row-btn").first
        btn.scroll_into_view_if_needed()
        expect(btn).to_be_in_viewport()
    finally:
        ctx.close()


@pytest.mark.parametrize("name", ["login", "register"])
def test_auth_pages_scroll_on_short_screens(browser, live_server, transactional_db, name):
    ctx = browser.new_context(viewport={"width": 360, "height": 480})
    page = ctx.new_page()
    try:
        page.goto(f"{live_server.url}{PAGES[name][0]}")
        expect(page.locator("h1")).to_be_visible()
        assert page.locator("h1").bounding_box()["y"] >= 0  # top of the card not cut off
        btn = page.locator("button[type=submit]")
        btn.scroll_into_view_if_needed()
        expect(btn).to_be_in_viewport()
    finally:
        ctx.close()


def test_translucent_badges_are_not_solid(browser, live_server, seeded):
    """Tailwind v4 dropped `bg-opacity-*`: badges/active nav were solid with unreadable text."""
    ctx, page = open_page(browser, live_server, "home", 1440)
    try:
        bg = page.locator("aside nav a", has_text="Home").evaluate("e => getComputedStyle(e).backgroundColor")
        assert "rgba" in bg or "/" in bg or "color(" in bg or "oklab" in bg, bg
        assert not bg.startswith("rgb(0, 240, 255)"), bg
    finally:
        ctx.close()
