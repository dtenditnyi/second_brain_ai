"""B-18 (JS error handling) and B-09 (AI/user text rendered as HTML) in the browser."""
import json
import re
from unittest import mock

import pytest
from playwright.sync_api import expect

from core.models import Task

pytestmark = pytest.mark.e2e

XSS = '<img src=x onerror="window.__xss=1"><b>bold</b>'


def test_settings_save_error_is_shown(logged_page, live_server, e2e_user):
    p = logged_page
    p.goto(f"{live_server.url}/settings/")
    p.fill("#display-name", "")
    p.get_by_role("button", name="Save System Configuration").click()
    expect(p.locator(".settings-container button").last).to_have_text(re.compile("cannot be empty", re.I))
    e2e_user.refresh_from_db()
    assert e2e_user.username == "e2e"


def test_add_task_error_is_reported(logged_page, live_server):
    p = logged_page
    p.goto(f"{live_server.url}/tasks/")
    p.get_by_role("button", name=re.compile("Add New Task")).click()
    p.fill("#task-title", "   ")  # passes HTML `required`, rejected by the API
    messages = []
    p.on("dialog", lambda d: (messages.append(d.message), d.accept()))
    p.get_by_role("button", name="Save Task").click()
    expect(p.locator("#task-modal")).to_be_visible()
    p.wait_for_timeout(500)
    assert any("title" in m.lower() for m in messages), messages
    assert Task.objects.count() == 0


def test_chat_api_error_message_is_shown(logged_page, live_server):
    p = logged_page
    p.goto(f"{live_server.url}/chat/")
    p.route("**/api/send-message/", lambda route: route.fulfill(
        status=400, content_type="application/json", body=json.dumps({"status": "error", "msg": "Server said no"})))
    p.fill("#chat-input", "hello")
    p.keyboard.press("Enter")
    expect(p.locator("#chat-feed")).to_contain_text("Server said no")


def test_chat_reply_is_rendered_as_text(logged_page, live_server):
    p = logged_page
    with mock.patch("core.rag_engine.ask_second_brain", return_value=XSS):
        p.goto(f"{live_server.url}/chat/")
        p.fill("#chat-input", "<i>user html</i>")
        p.keyboard.press("Enter")
        expect(p.locator("#chat-feed")).to_contain_text("<b>bold</b>")
    expect(p.locator("#chat-feed")).to_contain_text("<i>user html</i>")
    assert p.evaluate("window.__xss") is None
    assert p.locator("#chat-feed img").count() == 0


def test_home_report_is_rendered_as_text(logged_page, live_server):
    p = logged_page
    with mock.patch("core.rag_engine.ask_second_brain", return_value=XSS):
        p.click("#generate-report-btn")
        expect(p.locator("#ai-report-output")).to_contain_text("<b>bold</b>")
    assert p.evaluate("window.__xss") is None
