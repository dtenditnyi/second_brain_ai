"""Round 5 acceptance tests (docs/audit/round5/GOALS.md): web vault, PWA, weekly notes, 2FA, Obsidian in the browser.

Compact by design (PROMPT_LEAN §3): one test per goal / cluster of criteria. Every test starts as
xfail(strict=True); the marker is removed when the goal is done. Interfaces are the planned ones
(names may be refined when implementing — then the test is updated with a DECISIONS entry).
"""
import datetime
import json
import re
from pathlib import Path
from unittest import mock

import pytest
from django.test import Client

from tests import vault_helpers as vh
from tests.acceptance.test_round4 import NOTE, ScriptedProvider, post, real_git, remote, vclient, vuser  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
APP = ROOT / "ai_manager"
WEEK_DIR = "06 - Daily/2026 by weeks/Year 2 Semester 1"


def goal(g):
    return pytest.mark.xfail(strict=True, reason=f"R5 {g}")


# --------------------------------------------------------------------------- F1 navigation & search

def test_f1_search_filters_and_highlight(vclient):
    data = vclient.get("/api/notes/search/", {"q": "Аудит", "folder": "01 - Projects"}).json()
    assert data["results"] and all(r["path"].startswith("01 - Projects/") for r in data["results"])
    assert "<mark>" in data["results"][0]["snippet_html"]
    assert vclient.get("/api/notes/search/", {"q": "Аудит", "tag": "physics"}).json()["results"] == []


def test_f1_tags_page(vclient):
    html = vclient.get("/notes/tags/").content.decode()
    assert "#planning" in html and "#dev" in html


def test_f1_unlinked_mentions(vclient, remote, tmp_path):
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, "05 - Fleeting/упоминание.md", "Тут просто слово Университет без ссылки.\n")
    data = vclient.get("/api/notes/mentions/", {"path": "00 - Maps of content/Университет.md"}).json()
    assert "05 - Fleeting/упоминание.md" in [m["path"] for m in data["unlinked"]]
    assert data["backlinks"]


def test_f1_graph_data(vclient):
    local = vclient.get("/api/notes/graph/", {"path": "00 - Maps of content/Главная (Home).md"}).json()
    assert {"nodes", "edges"} <= set(local) and any("Университет" in n["name"] for n in local["nodes"])
    assert len(vclient.get("/api/notes/graph/").json()["nodes"]) >= len(local["nodes"])


@pytest.mark.e2e
def test_f1_quick_switcher_e2e(page, live_server, e2e_user, tmp_path, real_git, isolated_vault):
    from tests.e2e.conftest import login
    remote_ = vh.make_remote(tmp_path)
    s = e2e_user.settings
    s.github_repo_url = str(remote_)
    s.save()
    login(page, live_server, "e2e")
    page.goto(f"{live_server.url}/notes/")
    page.keyboard.press("Control+k")
    page.keyboard.type("SB")                       # alias of "Second Brain"
    page.locator("#quick-switcher [role=option]", has_text="Second Brain").first.wait_for()
    page.keyboard.press("Enter")
    page.locator("#workspace-content-area h1", has_text="Second Brain").wait_for()


# --------------------------------------------------------------------------- F2 render & Dataview-lite

def test_f2_callouts_and_checkbox_toggle_commits(vclient, remote, tmp_path):
    html = vclient.get("/api/get-note/", {"path": NOTE}).json()["html_content"]
    assert 'data-task-line' in html
    r = post(vclient, "/api/notes/toggle-task/", {"path": NOTE, "line": "- [/] Round 3", "status": "done"})
    assert r.status_code == 200 and "- [x] Round 3" in vh.remote_file(remote, NOTE, tmp_path)


def test_f2_embeds_and_attachment_safety(vclient, remote, tmp_path):
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, "05 - Fleeting/встройка.md", "![[Университет#Физика]]\n![[img.png]]\n")
    html = vclient.get("/api/get-note/", {"path": "05 - Fleeting/встройка.md"}).json()["html_content"]
    assert "note-embed" in html and "/attachments/" in html
    assert vclient.get("/attachments/", {"path": "../db.sqlite3"}).status_code in (400, 404)
    assert vclient.get("/attachments/", {"path": ".git/config"}).status_code in (400, 404)


def test_f2_dataview_list_table_task(vuser):
    from core import dataview
    out = dataview.run(vuser, 'TABLE status, date FROM "01 - Projects" WHERE status = "active" SORT file.name LIMIT 5')
    assert out["kind"] == "table" and out["rows"] and len(out["rows"]) <= 5
    assert dataview.run(vuser, "LIST FROM #planning")["rows"]
    assert all(t["status"] != "done" for t in dataview.run(vuser, "TASK WHERE !completed")["rows"])


def test_f2_dataview_unsupported_and_sandbox(vuser):
    from core import dataview
    assert dataview.run(vuser, 'CALENDAR file.mtime')["kind"] == "unsupported"
    assert dataview.run(vuser, 'LIST FROM "../"')["kind"] == "error"
    assert dataview.run(vuser, 'dv.pages().forEach(p => fetch("x"))')["kind"] == "unsupported"


def test_f2_math_mermaid_assets_local():
    vendor = {p.name for p in (APP / "static" / "vendor").iterdir()}
    assert any("katex" in n for n in vendor) and any("mermaid" in n for n in vendor)


# --------------------------------------------------------------------------- F3 weekly notes

def test_f3_this_week_opens_or_creates(vclient, remote, tmp_path):
    r = post(vclient, "/api/weekly/this-week/", {"today": "2026-11-11"})
    data = r.json()
    assert r.status_code == 200 and data["path"].startswith(WEEK_DIR + "/") and data["created"] is True
    assert "type: weekly" in vh.remote_file(remote, data["path"], tmp_path)
    again = post(vclient, "/api/weekly/this-week/", {"today": "2026-11-11"}).json()
    assert again["path"] == data["path"] and again["created"] is False


def test_f3_carry_over_tasks_preview_and_apply(vclient, remote, tmp_path):
    week = post(vclient, "/api/weekly/this-week/", {"today": "2026-11-11"}).json()["path"]
    preview = post(vclient, "/api/weekly/carry-over/", {"to": week, "preview": True}).json()
    assert "Повторить DSA" in preview["diff"]
    before = len(vh.remote_log(remote))
    post(vclient, "/api/weekly/carry-over/", {"to": week})
    assert len(vh.remote_log(remote)) == before + 1
    old = vh.remote_file(remote, f"{WEEK_DIR}/Fifth week of 2nd year.md", tmp_path)
    assert "- [>] Повторить DSA" in old and "Повторить DSA" in vh.remote_file(remote, week, tmp_path)


def test_f3_week_calendar_lists_weeks(vclient):
    weeks = vclient.get("/api/weekly/calendar/").json()["weeks"]
    assert any(w["path"].endswith("Fifth week of 2nd year.md") for w in weeks)


# --------------------------------------------------------------------------- F4 PWA

def test_f4_manifest_and_sw_served(client):
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200 and json.loads(manifest.content)["icons"]
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw["Content-Type"] and sw.get("Service-Worker-Allowed", "/") == "/"


def test_f4_logout_clears_cache_header(auth_client):
    r = auth_client.post("/logout/")
    assert '"cache"' in r.get("Clear-Site-Data", "") or "sb-clear-cache" in r.content.decode()


@pytest.mark.e2e
def test_f4_offline_banner_and_capture_queue_e2e(page, live_server, e2e_user, tmp_path, real_git, isolated_vault):
    from tests.e2e.conftest import login
    remote_ = vh.make_remote(tmp_path)
    s = e2e_user.settings
    s.github_repo_url = str(remote_)
    s.save()
    login(page, live_server, "e2e")
    page.goto(f"{live_server.url}/")
    page.context.set_offline(True)
    page.locator("#offline-banner").wait_for()
    page.fill("#quick-capture-input", "офлайн мысль")
    page.keyboard.press("Enter")
    page.context.set_offline(False)
    page.locator("#quick-capture-status", has_text=re.compile("Сохранено|Saved")).wait_for()


# --------------------------------------------------------------------------- F5 home

def test_f5_home_dashboard_blocks(vclient):
    html = vclient.get("/").content.decode()
    for block in ("tasks-today", "current-week", "recent-notes", "quick-capture-input", "/chat/"):
        assert block in html, block


def test_f5_quick_capture_from_home(vclient, remote, tmp_path, settings):
    r = post(vclient, "/api/capture/", {"text": "с главной"})
    assert r.status_code == 200 and "с главной" in vh.remote_file(remote, settings.CAPTURE_INBOX_NOTE, tmp_path)


# --------------------------------------------------------------------------- F6 / F7 docs + compose

def test_f6_compose_obsidian_profile():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    block = compose.split("  obsidian:", 1)[1].split("\n  tunnel:", 1)[0] if "  obsidian:" in compose else ""
    assert "lscr.io/linuxserver/obsidian" in block and "profiles:" in block and "shm_size" in block
    assert "ports:" not in block and "restart: unless-stopped" in block


def test_f6_deploy_doc_obsidian():
    doc = (ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    assert "linuxserver/obsidian" in doc and "obsidian-git" in doc and "sudo" in doc and "Cloudflare Access" in doc


def test_f7_totp_enable_login_backup_disable(vclient, vuser):
    import pyotp
    setup = vclient.get("/api/2fa/setup/").json()
    assert setup["otpauth_url"].startswith("otpauth://") and setup["qr_svg"].startswith("<svg")
    code = pyotp.TOTP(setup["secret"]).now()
    r = post(vclient, "/api/2fa/enable/", {"code": code})
    backup = r.json()["backup_codes"]
    assert r.status_code == 200 and len(backup) >= 8
    c = Client()
    c.post("/login/", {"username": vuser.username, "password": "Str0ng-Pass-123!"})
    assert c.get("/").status_code == 302                       # second step required
    assert c.post("/login/2fa/", {"code": backup[0]}).status_code == 302 and c.get("/").status_code == 200
    assert post(vclient, "/api/2fa/disable/", {"code": "000000"}).status_code == 400


def test_f7_api_not_affected_by_2fa(vuser):
    from core.models import ApiToken
    s = vuser.settings
    s._meta.get_field("totp_enabled")                       # the 2FA field exists
    s.totp_enabled = True
    s.save()
    _, raw = ApiToken.create_for(vuser, name="bot", scopes=["read"])
    assert Client().get("/api/v1/sync/", HTTP_AUTHORIZATION=f"Bearer {raw}").status_code == 200


def test_f7_deploy_doc_access():
    doc = (ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    assert "Cloudflare Access" in doc and "Bypass" in doc and "/api/v1/" in doc and "TOTP" in doc


# --------------------------------------------------------------------------- F8 responsive

@pytest.mark.e2e
@pytest.mark.responsive
@pytest.mark.parametrize("url", ["/", "/notes/tags/", "/notes/graph/", "/weekly/"])
@pytest.mark.parametrize("width", [320, 768, 1440])
def test_f8_new_pages_responsive(browser, live_server, e2e_user, tmp_path, real_git, isolated_vault, url, width):
    from tests.e2e.conftest import login
    from tests.e2e.responsive_helpers import METRICS_JS
    remote_ = vh.make_remote(tmp_path)
    s = e2e_user.settings
    s.github_repo_url = str(remote_)
    s.save()
    ctx = browser.new_context(viewport={"width": width, "height": 800})
    page = ctx.new_page()
    try:
        login(page, live_server, "e2e")
        resp = page.goto(live_server.url + url)
        assert resp.status == 200 and page.locator("[data-r5-page]").count() == 1   # new/updated R5 page
        m = page.evaluate(METRICS_JS)
        assert m["docScroll"] <= m["vw"] and m["overflowing"] == [], m["overflowing"]
        if width < 1024:
            assert m["smallTargets"] == [], m["smallTargets"]
    finally:
        ctx.close()


# --------------------------------------------------------------------------- end to end

@pytest.mark.e2e
def test_e2e_owner_journey(page, live_server, e2e_user, tmp_path, real_git, isolated_vault):
    """2FA login → this week → bot capture → API task → Obsidian edit → editor → agent apply/revert → search."""
    import pyotp
    from core import agent, twofa
    from core.models import ApiToken
    from tests.conftest import PASSWORD
    remote_ = vh.make_remote(tmp_path)
    tasks_rel = vh.TASKS_NOTE
    s = e2e_user.settings
    secret = twofa.new_secret()
    s.github_repo_url, s.totp_enabled, s.totp_secret = str(remote_), True, secret
    s.save()
    _, bot = ApiToken.create_for(e2e_user, name="link2note", scopes=["read", "write", "ai"])
    auth = {"Authorization": f"Bearer {bot}"}
    base = live_server.url

    # 1) password → second step (TOTP) → home
    page.goto(f"{base}/login/")
    page.fill("#id_username", "e2e")
    page.fill("#id_password", PASSWORD)
    page.click("button[type=submit]")
    page.wait_for_url(f"{base}/login/2fa/")
    page.fill("#id_code", pyotp.TOTP(secret).now())
    page.click("button[type=submit]")
    page.wait_for_url(f"{base}/")
    page.locator("#quick-capture-input").wait_for()

    # 2) «Эта неделя» creates this week's note and opens it
    page.goto(f"{base}/weekly/")
    page.click("#this-week-btn")
    page.wait_for_url(re.compile(r"/notes/\?path=06"))
    week = page.evaluate("new URLSearchParams(location.search).get('path')")
    assert week.startswith(WEEK_DIR + "/") and "type: weekly" in vh.remote_file(remote_, week, tmp_path)

    # 3) capture via the API with the bot token → «Входящие»
    r = page.request.post(f"{base}/api/v1/capture", data={"text": "мысль от бота"},
                          headers={**auth, "Idempotency-Key": "journey-1"})
    assert r.status == 201
    inbox = r.json()["path"]
    assert "мысль от бота" in vh.remote_file(remote_, inbox, tmp_path)

    # 4) a task via the API is visible on the site
    r = page.request.post(f"{base}/api/v1/tasks", data={"text": "Купить молоко", "tags": ["cooking"]}, headers=auth)
    assert r.status == 201, r.text()
    page.goto(f"{base}/tasks/")
    page.get_by_text("Купить молоко").first.wait_for()

    # 5) the task is changed "in Obsidian" (a commit in a 2nd clone) → visible after sync
    phone = vh.clone(remote_, tmp_path / "phone")
    note = (phone / tasks_rel).read_bytes().decode("utf-8")
    vh.commit_and_push(phone, tasks_rel, note.replace("Купить молоко", "Купить овсяное молоко"), "obsidian: edit task")
    page.click("#tasks-refresh")
    page.get_by_text("Купить овсяное молоко").first.wait_for()

    # 6) edit a note in the editor
    page.goto(f"{base}/notes/?path={NOTE}")
    page.get_by_role("button", name=re.compile("Edit")).click()
    editor = page.locator(".cm-content")
    editor.wait_for()
    editor.click()
    page.keyboard.press("Control+End")
    page.keyboard.type("\nСтрока из редактора про Университет")
    page.keyboard.press("Control+s")
    page.locator("#note-save-status", has_text=re.compile("Saved|Сохранено")).wait_for()
    page.keyboard.press("Escape")

    # 7) the agent appends → diff → apply → revert
    prov = ScriptedProvider([{"tools": [("append_to_note", {"path": NOTE, "text": "Строка от ИИ"})]},
                             {"text": "Дописал."}])
    with mock.patch.object(agent, "default_provider", lambda user: prov):
        page.goto(f"{base}/chat/")
        page.check("#agent-mode-toggle")
        page.fill("#chat-input", "Допиши заметку")
        page.keyboard.press("Enter")
        card = page.locator(".agent-diff-card").last
        card.wait_for()
    assert "Строка от ИИ" in card.inner_text()
    card.get_by_role("button", name="Применить всё").click()
    card.locator(".agent-applied", has_text=re.compile("Применено|Applied")).wait_for()
    assert "Строка от ИИ" in vh.remote_file(remote_, NOTE, tmp_path)
    card.get_by_role("button", name="Откатить").click()
    card.locator(".agent-applied", has_text=re.compile("Откат|Reverted")).wait_for()

    # 8) search, backlinks / mentions and Dataview see the new data
    found = page.request.get(f"{base}/api/notes/search/", params={"q": "редактора"}).json()["results"]
    assert [x["path"] for x in found] == [NOTE] and "<mark>" in found[0]["snippet_html"]
    assert page.request.get(f"{base}/api/notes/search/", params={"q": "мысль от бота"}).json()["results"]
    links = page.request.get(f"{base}/api/notes/mentions/", params={"path": "00 - Maps of content/Университет.md"}).json()
    assert NOTE in [m["path"] for m in links["unlinked"]]
    tasks_html = page.request.get(f"{base}/api/get-note/", params={"path": tasks_rel}).json()["html_content"]
    assert "dataview-task" in tasks_html and "Round 3" in tasks_html
    page.goto(f"{base}/notes/?path={NOTE}")
    page.locator("#workspace-content-area", has_text="Строка из редактора").wait_for()
    assert "Строка от ИИ" not in page.locator("#workspace-content-area").inner_text()

    # 9) git history intact: every step is a commit, the owner's own text untouched
    subjects = [subject for _author, subject in vh.remote_log(remote_)]
    assert subjects[-1] == "seed vault" and "obsidian: edit task" in subjects
    assert any(sub.startswith("weekly:") for sub in subjects) and any("capture" in sub for sub in subjects)
    assert any(sub.startswith("Revert") or "revert" in sub.lower() for sub in subjects)
    final_tasks = vh.remote_file(remote_, tasks_rel, tmp_path)
    assert "Личный текст владельца — не трогать." in final_tasks and "Купить овсяное молоко" in final_tasks
    assert vh.remote_file(remote_, "00 - Maps of content/Университет.md", tmp_path) == \
        vh.FIXTURE_VAULT["00 - Maps of content/Университет.md"]
