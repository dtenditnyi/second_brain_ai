"""Round 2 user flows in a real browser (Edge): task status control, chat
search scope + smart toggle, token field, Core Matrix self-protection and the
mobile menu (backdrop, Esc, scroll lock)."""
import re
from unittest import mock

import pytest
from playwright.sync_api import expect

from core.models import ChatMessage, Task, UserSettings
from tests.conftest import write_note
from tests.e2e.conftest import login

pytestmark = pytest.mark.e2e


def test_task_status_select_on_tasks_page(logged_page, live_server, e2e_user, browser_errors):
    t = Task.objects.create(user=e2e_user, title="move-me")
    p = logged_page
    p.goto(f"{live_server.url}/tasks/")
    with p.expect_navigation():
        p.locator(f'.task-status-select[data-id="{t.id}"]').first.select_option("in_progress")
    t.refresh_from_db()
    assert t.status == "in_progress"
    expect(p.locator(f'.task-status-select[data-id="{t.id}"]').first).to_have_value("in_progress")
    with p.expect_navigation():
        p.locator(f'.task-status-select[data-id="{t.id}"]').first.select_option("done")
    t.refresh_from_db()
    assert t.status == "done"
    assert browser_errors == []


def test_task_status_select_on_home_board(logged_page, live_server, e2e_user):
    t = Task.objects.create(user=e2e_user, title="board-card")
    p = logged_page
    p.reload()
    with p.expect_navigation():
        p.locator(f'.task-status-select[data-id="{t.id}"]').select_option("in_progress")
    t.refresh_from_db()
    assert t.status == "in_progress"
    column = p.locator("h3", has_text="In Progress").locator("..")
    expect(column).to_contain_text("board-card")


def test_rejected_status_change_is_reverted_and_reported(logged_page, live_server, e2e_user):
    t = Task.objects.create(user=e2e_user, title="stubborn")
    p = logged_page
    p.goto(f"{live_server.url}/tasks/")
    p.route("**/api/update-task/", lambda route: route.fulfill(
        status=400, content_type="application/json", body='{"status": "error", "msg": "Unknown task status."}'))
    select = p.locator(f'.task-status-select[data-id="{t.id}"]').first
    select.select_option("in_progress")
    expect(p.locator("#task-error-toast")).to_contain_text("Unknown task status")
    expect(select).to_have_value("todo")


def test_smart_toggle_and_report_mode(logged_page, live_server, e2e_user, isolated_vault):
    write_note(isolated_vault, e2e_user, "Alpha", "x")
    p = logged_page
    with mock.patch("core.rag_engine.ask_second_brain", return_value="smart-reply") as ask:
        p.goto(f"{live_server.url}/chat/")
        p.check("#smart-answer-toggle")
        p.fill("#chat-input", "deep question")
        p.keyboard.press("Enter")
        expect(p.get_by_text("smart-reply")).to_be_visible()
        assert ask.call_args.kwargs["smart"] is True
    with mock.patch("core.rag_engine.ask_second_brain", return_value="Report text") as ask:
        p.goto(f"{live_server.url}/")
        p.click("#generate-report-btn")
        expect(p.locator("#ai-report-output")).to_contain_text("Report text")
        assert ask.call_args.kwargs["smart"] is True and ask.call_args.kwargs["history"] == []
    # Q3: the report is not in the chat history
    assert not ChatMessage.objects.filter(content="Report text").exists()


def test_token_field_is_empty_and_keeps_or_clears_token(logged_page, live_server, e2e_user):
    s = UserSettings.objects.get(user=e2e_user)
    s.github_token = "ghp_very_secret"
    s.save()
    p = logged_page
    p.goto(f"{live_server.url}/settings/")
    assert "ghp_very_secret" not in p.content()
    expect(p.locator("#github-token")).to_have_value("")
    expect(p.locator("#github-token")).to_have_attribute("placeholder", re.compile("Token saved"))
    p.get_by_role("button", name="Save System Configuration").click()
    expect(p.get_by_role("button", name="Configuration Saved Successfully")).to_be_visible()
    assert UserSettings.objects.get(user=e2e_user).github_token == "ghp_very_secret"
    p.check("#clear-github-token")
    expect(p.locator("#github-token")).to_be_disabled()
    # The status already says "Settings saved." from the first save: wait for THIS request (race, R5 full run).
    with p.expect_response(lambda r: "/api/save-settings/" in r.url) as saved:
        p.get_by_role("button", name="Save System Configuration").click()
    assert saved.value.ok
    expect(p.locator("#settings-status")).to_have_text("Settings saved.")
    assert UserSettings.objects.get(user=e2e_user).github_token == ""


def test_display_name_change_keeps_login(logged_page, live_server, e2e_user):
    p = logged_page
    p.goto(f"{live_server.url}/settings/")
    p.fill("#display-name", "Neo")
    p.get_by_role("button", name="Save System Configuration").click()
    expect(p.locator("#settings-status")).to_have_text("Settings saved.")
    e2e_user.refresh_from_db()
    assert e2e_user.username == "e2e"
    p.goto(f"{live_server.url}/")
    expect(p.locator("h1").first).to_contain_text("Welcome back, Neo")
    expect(p.locator("#main-sidebar")).to_contain_text("Neo")


def test_core_matrix_own_row_is_protected(page, live_server, e2e_admin, e2e_user, browser_errors):
    login(page, live_server, "e2eroot")
    page.goto(f"{live_server.url}/system-matrix/")
    own = page.locator(f'table[data-model="users"] tr[data-id="{e2e_admin.id}"]')
    expect(own.locator('select[name="is_superuser"]')).to_be_disabled()
    expect(own.locator(".delete-row-btn")).to_be_disabled()
    other = page.locator(f'table[data-model="users"] tr[data-id="{e2e_user.id}"]')
    expect(other.locator(".delete-row-btn")).to_be_enabled()
    # Committing the own row still works and keeps the superuser flag.
    own.locator('input[name="email"]').fill("root@new.io")
    own.locator(".save-row-btn").click()
    expect(own.locator(".save-row-btn")).to_have_text("Success")
    e2e_admin.refresh_from_db()
    assert e2e_admin.is_superuser and e2e_admin.email == "root@new.io"
    with page.expect_navigation():
        page.get_by_role("link", name="Back to Dashboard").click()
    assert page.url == f"{live_server.url}/"
    assert browser_errors == []


@pytest.mark.parametrize("close_by", ["backdrop", "escape", "button"])
def test_mobile_menu_backdrop_escape_and_scroll_lock(logged_page, live_server, close_by):
    p = logged_page
    p.set_viewport_size({"width": 390, "height": 844})
    p.goto(f"{live_server.url}/tasks/")
    sidebar = p.locator("#main-sidebar")
    p.click("#mobile-menu-open")
    p.wait_for_timeout(400)
    assert sidebar.bounding_box()["x"] >= 0
    expect(p.locator("#menu-backdrop")).to_have_class(re.compile("is-open"))
    expect(p.locator("body")).to_have_class(re.compile("scroll-locked"))
    expect(p.locator("#mobile-menu-open")).to_have_attribute("aria-expanded", "true")
    if close_by == "backdrop":
        p.mouse.click(370, 400)  # right of the 288px menu, on the dimmed backdrop
    elif close_by == "escape":
        p.keyboard.press("Escape")
    else:
        p.click("#mobile-menu-close")
    p.wait_for_timeout(400)
    assert sidebar.bounding_box()["x"] + sidebar.bounding_box()["width"] <= 0
    expect(p.locator("body")).not_to_have_class(re.compile("scroll-locked"))
    expect(p.locator("#mobile-menu-open")).to_have_attribute("aria-expanded", "false")
