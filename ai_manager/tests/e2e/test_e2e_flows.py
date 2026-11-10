"""Main user scenarios in a real browser (MS Edge)."""
import re
from unittest import mock

import pytest
from playwright.sync_api import expect

from core.models import Task, ChatMessage, UserSettings
from tests.conftest import PASSWORD, write_note
from tests.e2e.conftest import login

pytestmark = pytest.mark.e2e


def test_register_then_land_on_home(page, live_server, transactional_db, browser_errors):
    page.goto(f"{live_server.url}/register/")
    page.fill("#id_username", "fresh")
    page.fill("#id_password1", "Qwerty-Long-9876")
    page.fill("#id_password2", "Qwerty-Long-9876")
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/")
    expect(page.locator("h2").first).to_contain_text("Welcome back, fresh")
    assert browser_errors == []


def test_login_failure_shows_message(page, live_server, e2e_user):
    page.goto(f"{live_server.url}/login/")
    page.fill("#id_username", "e2e")
    page.fill("#id_password", "wrong")
    page.click("button[type=submit]")
    expect(page.get_by_text("Authentication failed")).to_be_visible()


@pytest.mark.parametrize("path", ["/", "/chat/", "/notes/", "/tasks/", "/settings/"])
def test_pages_have_no_browser_errors(logged_page, live_server, browser_errors, path):
    logged_page.goto(f"{live_server.url}{path}")
    logged_page.wait_for_load_state("networkidle")
    expect(logged_page.locator("#sidebar-sync-percent")).to_have_text(re.compile(r"\d+%"))
    assert browser_errors == []


def test_add_task_and_complete_it(logged_page, live_server, e2e_user, browser_errors):
    p = logged_page
    p.goto(f"{live_server.url}/tasks/")
    p.get_by_role("button", name=re.compile("Add New Task")).click()
    expect(p.locator("#task-modal")).to_be_visible()
    p.fill("#task-title", "Ship the audit")
    p.select_option("#task-priority", "urgent")
    p.fill("#task-date", "2026-12-24")
    p.fill("#task-tags", "audit")
    p.get_by_role("button", name="Save Task").click()
    expect(p.get_by_text("Ship the audit")).to_be_visible()
    expect(p.locator("#task-modal")).to_be_hidden()
    t = Task.objects.get(title="Ship the audit")
    assert (t.priority, str(t.due_date), t.tags, t.user_id) == ("urgent", "2026-12-24", "audit", e2e_user.id)
    # complete it via checkbox → moves to Completed section, sidebar shows 100%
    with p.expect_navigation():
        p.locator(f'.task-checkbox[data-id="{t.id}"]').check()
    t.refresh_from_db()
    assert t.status == "done"
    expect(p.locator("#sidebar-sync-percent")).to_have_text("100%")
    assert [e for e in browser_errors if "ERR_ABORTED" not in e] == []


def test_settings_save_persists_and_applies_theme(logged_page, live_server, e2e_user, browser_errors):
    p = logged_page
    p.goto(f"{live_server.url}/settings/")
    p.select_option("#theme-select", "light")
    expect(p.locator("html")).to_have_attribute("data-theme", "light")
    p.check('input[name="accent-color"][value="green"]')
    p.select_option("#ai-strategy", "cloud_only")
    p.fill("#github-repo", "https://github.com/u/vault.git")
    p.get_by_role("button", name="Save System Configuration").click()
    expect(p.get_by_role("button", name="Configuration Saved Successfully")).to_be_visible()
    s = UserSettings.objects.get(user=e2e_user)
    assert (s.theme, s.accent_color, s.ai_strategy, s.github_repo_url) == ("light", "green", "cloud_only", "https://github.com/u/vault.git")
    p.reload()
    expect(p.locator("html")).to_have_attribute("data-accent", "green")
    assert browser_errors == []


def test_chat_send_message_with_mocked_ai(logged_page, live_server, e2e_user, browser_errors):
    p = logged_page
    with mock.patch("core.rag_engine.ask_second_brain", return_value="Mocked answer\nsecond line"):
        p.goto(f"{live_server.url}/chat/")
        p.fill("#chat-input", "What is in my vault?")
        p.keyboard.press("Enter")
        expect(p.get_by_text("Mocked answer")).to_be_visible()
    assert list(ChatMessage.objects.filter(user=e2e_user).values_list("role", flat=True)) == ["user", "ai"]
    assert browser_errors == []


def test_home_search_hands_query_to_chat(logged_page, live_server, e2e_user):
    p = logged_page
    with mock.patch("core.rag_engine.ask_second_brain", return_value="Search answer"):
        p.fill("#global-search-input", "find my notes")
        p.keyboard.press("Enter")
        p.wait_for_url(f"{live_server.url}/chat/")
        expect(p.get_by_text("Search answer")).to_be_visible()
    assert ChatMessage.objects.filter(user=e2e_user, role="user", content="find my notes").exists()


def test_chat_context_modal_select_all_and_apply(logged_page, live_server, e2e_user, isolated_vault):
    for n in ["Alpha", "Beta", "Gamma"]:
        write_note(isolated_vault, e2e_user, n, "x")
    p = logged_page
    p.goto(f"{live_server.url}/chat/")
    p.click("#add-documents-button")
    expect(p.locator("#context-modal")).to_be_visible()
    p.uncheck("#select-all-checkbox")
    expect(p.locator("#selected-files-count")).to_have_text("0 selected")
    p.check('.file-checkbox[value="Beta"]')
    expect(p.locator("#selected-files-count")).to_have_text("1 selected")
    p.click("#apply-context-button")
    expect(p.locator("#context-modal")).to_be_hidden()
    expect(p.locator("#context-file-list li")).to_have_count(1)
    expect(p.locator("#context-file-list")).to_contain_text("Beta.md")
    p.click("#add-documents-button")
    p.keyboard.press("Escape")
    expect(p.locator("#context-modal")).to_be_hidden()


def test_notes_open_note_follow_wikilink_and_backlink(logged_page, live_server, e2e_user, isolated_vault, browser_errors):
    write_note(isolated_vault, e2e_user, "Home Note", "# Hello\nGo to [[Target]].")
    write_note(isolated_vault, e2e_user, "Target", "Target body text")
    p = logged_page
    p.goto(f"{live_server.url}/notes/")
    p.locator('.file-item[data-filename="Home Note"]').click()
    expect(p.locator("#workspace-content-area h1").first).to_have_text("Home Note")
    p.locator("#workspace-content-area .wiki-link").click()
    expect(p.locator("#workspace-content-area")).to_contain_text("Target body text")
    expect(p.locator("#backlinks-counter-label")).to_have_text("1 note link here")
    p.locator(".backlink-card").click()
    expect(p.locator("#workspace-content-area h1").first).to_have_text("Home Note")
    assert browser_errors == []


def test_notes_deep_link_from_chat(logged_page, live_server, e2e_user, isolated_vault):
    write_note(isolated_vault, e2e_user, "Deep", "deep body")
    p = logged_page
    p.goto(f"{live_server.url}/notes/?file=Deep")
    expect(p.locator("#workspace-content-area")).to_contain_text("deep body")
    assert "file=" not in p.url


def test_logout(logged_page, live_server):
    logged_page.get_by_role("link", name=re.compile("Log Out")).click()
    logged_page.wait_for_url(re.compile(r"/login/"))


def test_admin_matrix_edit_and_drop(page, live_server, e2e_admin, e2e_user, browser_errors):
    t = Task.objects.create(user=e2e_user, title="admin-edit-me")
    login(page, live_server, "e2eroot")
    page.goto(f"{live_server.url}/system-matrix/")
    page.click('[data-tab="tasks-table"]')
    row = page.locator(f'table[data-model="tasks"] tr[data-id="{t.id}"]')
    row.locator('input[name="title"]').fill("edited-by-admin")
    row.locator(".save-row-btn").click()
    expect(row.locator(".save-row-btn")).to_have_text("Success")
    t.refresh_from_db()
    assert t.title == "edited-by-admin"
    page.once("dialog", lambda d: d.accept())
    row.locator(".delete-row-btn").click()
    expect(row).to_have_count(0)
    assert not Task.objects.filter(id=t.id).exists()
    assert browser_errors == []


def test_mobile_menu_opens_and_closes(logged_page, live_server):
    p = logged_page
    p.set_viewport_size({"width": 390, "height": 844})
    p.goto(f"{live_server.url}/tasks/")
    sidebar = p.locator("#main-sidebar")
    expect(p.locator("#mobile-menu-open")).to_be_visible()
    assert sidebar.bounding_box()["x"] < 0  # off-canvas
    p.click("#mobile-menu-open")
    p.wait_for_timeout(400)
    assert sidebar.bounding_box()["x"] >= 0
    p.click("#mobile-menu-close")
    p.wait_for_timeout(400)
    assert sidebar.bounding_box()["x"] < 0
