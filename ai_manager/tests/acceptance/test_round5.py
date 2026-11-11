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

@goal("G-F1")
def test_f1_search_filters_and_highlight(vclient):
    data = vclient.get("/api/notes/search/", {"q": "Аудит", "folder": "01 - Projects"}).json()
    assert data["results"] and all(r["path"].startswith("01 - Projects/") for r in data["results"])
    assert "<mark>" in data["results"][0]["snippet_html"]
    assert vclient.get("/api/notes/search/", {"q": "Аудит", "tag": "physics"}).json()["results"] == []


@goal("G-F1")
def test_f1_tags_page(vclient):
    html = vclient.get("/notes/tags/").content.decode()
    assert "#planning" in html and "#dev" in html


@goal("G-F1")
def test_f1_unlinked_mentions(vclient, remote, tmp_path):
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, "05 - Fleeting/упоминание.md", "Тут просто слово Университет без ссылки.\n")
    data = vclient.get("/api/notes/mentions/", {"path": "00 - Maps of content/Университет.md"}).json()
    assert "05 - Fleeting/упоминание.md" in [m["path"] for m in data["unlinked"]]
    assert data["backlinks"]


@goal("G-F1")
def test_f1_graph_data(vclient):
    local = vclient.get("/api/notes/graph/", {"path": "00 - Maps of content/Главная (Home).md"}).json()
    assert {"nodes", "edges"} <= set(local) and any("Университет" in n["name"] for n in local["nodes"])
    assert len(vclient.get("/api/notes/graph/").json()["nodes"]) >= len(local["nodes"])


@pytest.mark.e2e
@goal("G-F1")
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

@goal("G-F2")
def test_f2_callouts_and_checkbox_toggle_commits(vclient, remote, tmp_path):
    html = vclient.get("/api/get-note/", {"path": NOTE}).json()["html_content"]
    assert 'data-task-line' in html
    r = post(vclient, "/api/notes/toggle-task/", {"path": NOTE, "line": "- [/] Round 3", "status": "done"})
    assert r.status_code == 200 and "- [x] Round 3" in vh.remote_file(remote, NOTE, tmp_path)


@goal("G-F2")
def test_f2_embeds_and_attachment_safety(vclient, remote, tmp_path):
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, "05 - Fleeting/встройка.md", "![[Университет#Физика]]\n![[img.png]]\n")
    html = vclient.get("/api/get-note/", {"path": "05 - Fleeting/встройка.md"}).json()["html_content"]
    assert "note-embed" in html and "/attachments/" in html
    assert vclient.get("/attachments/", {"path": "../db.sqlite3"}).status_code in (400, 404)
    assert vclient.get("/attachments/", {"path": ".git/config"}).status_code in (400, 404)


@goal("G-F2")
def test_f2_dataview_list_table_task(vuser):
    from core import dataview
    out = dataview.run(vuser, 'TABLE status, date FROM "01 - Projects" WHERE status = "active" SORT file.name LIMIT 5')
    assert out["kind"] == "table" and out["rows"] and len(out["rows"]) <= 5
    assert dataview.run(vuser, "LIST FROM #planning")["rows"]
    assert all(t["status"] != "done" for t in dataview.run(vuser, "TASK WHERE !completed")["rows"])


@goal("G-F2")
def test_f2_dataview_unsupported_and_sandbox(vuser):
    from core import dataview
    assert dataview.run(vuser, 'CALENDAR file.mtime')["kind"] == "unsupported"
    assert dataview.run(vuser, 'LIST FROM "../"')["kind"] == "error"
    assert dataview.run(vuser, 'dv.pages().forEach(p => fetch("x"))')["kind"] == "unsupported"


@goal("G-F2")
def test_f2_math_mermaid_assets_local():
    vendor = {p.name for p in (APP / "static" / "vendor").iterdir()}
    assert any("katex" in n for n in vendor) and any("mermaid" in n for n in vendor)


# --------------------------------------------------------------------------- F3 weekly notes

@goal("G-F3")
def test_f3_this_week_opens_or_creates(vclient, remote, tmp_path):
    r = post(vclient, "/api/weekly/this-week/", {"today": "2026-11-11"})
    data = r.json()
    assert r.status_code == 200 and data["path"].startswith(WEEK_DIR + "/") and data["created"] is True
    assert "type: weekly" in vh.remote_file(remote, data["path"], tmp_path)
    again = post(vclient, "/api/weekly/this-week/", {"today": "2026-11-11"}).json()
    assert again["path"] == data["path"] and again["created"] is False


@goal("G-F3")
def test_f3_carry_over_tasks_preview_and_apply(vclient, remote, tmp_path):
    week = post(vclient, "/api/weekly/this-week/", {"today": "2026-11-11"}).json()["path"]
    preview = post(vclient, "/api/weekly/carry-over/", {"to": week, "preview": True}).json()
    assert "Повторить DSA" in preview["diff"]
    before = len(vh.remote_log(remote))
    post(vclient, "/api/weekly/carry-over/", {"to": week})
    assert len(vh.remote_log(remote)) == before + 1
    old = vh.remote_file(remote, f"{WEEK_DIR}/Fifth week of 2nd year.md", tmp_path)
    assert "- [>] Повторить DSA" in old and "Повторить DSA" in vh.remote_file(remote, week, tmp_path)


@goal("G-F3")
def test_f3_week_calendar_lists_weeks(vclient):
    weeks = vclient.get("/api/weekly/calendar/").json()["weeks"]
    assert any(w["path"].endswith("Fifth week of 2nd year.md") for w in weeks)


# --------------------------------------------------------------------------- F4 PWA

@goal("G-F4")
def test_f4_manifest_and_sw_served(client):
    manifest = client.get("/manifest.webmanifest")
    assert manifest.status_code == 200 and json.loads(manifest.content)["icons"]
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and "javascript" in sw["Content-Type"] and sw.get("Service-Worker-Allowed", "/") == "/"


@goal("G-F4")
def test_f4_logout_clears_cache_header(auth_client):
    r = auth_client.post("/logout/")
    assert '"cache"' in r.get("Clear-Site-Data", "") or "sb-clear-cache" in r.content.decode()


@pytest.mark.e2e
@goal("G-F4")
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

@goal("G-F5")
def test_f5_home_dashboard_blocks(vclient):
    html = vclient.get("/").content.decode()
    for block in ("tasks-today", "current-week", "recent-notes", "quick-capture-input", "/chat/"):
        assert block in html, block


@goal("G-F5")
def test_f5_quick_capture_from_home(vclient, remote, tmp_path, settings):
    r = post(vclient, "/api/capture/", {"text": "с главной"})
    assert r.status_code == 200 and "с главной" in vh.remote_file(remote, settings.CAPTURE_INBOX_NOTE, tmp_path)


# --------------------------------------------------------------------------- F6 / F7 docs + compose

@goal("G-F6")
def test_f6_compose_obsidian_profile():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    block = compose.split("  obsidian:", 1)[1].split("\n  tunnel:", 1)[0] if "  obsidian:" in compose else ""
    assert "lscr.io/linuxserver/obsidian" in block and "profiles:" in block and "shm_size" in block
    assert "ports:" not in block and "restart: unless-stopped" in block


@goal("G-F6")
def test_f6_deploy_doc_obsidian():
    doc = (ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    assert "linuxserver/obsidian" in doc and "obsidian-git" in doc and "sudo" in doc and "Cloudflare Access" in doc


@goal("G-F7")
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


@goal("G-F7")
def test_f7_api_not_affected_by_2fa(vuser):
    from core.models import ApiToken
    s = vuser.settings
    s._meta.get_field("totp_enabled")                       # the 2FA field exists
    s.totp_enabled = True
    s.save()
    _, raw = ApiToken.create_for(vuser, name="bot", scopes=["read"])
    assert Client().get("/api/v1/sync/", HTTP_AUTHORIZATION=f"Bearer {raw}").status_code == 200


@goal("G-F7")
def test_f7_deploy_doc_access():
    doc = (ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    assert "Cloudflare Access" in doc and "Bypass" in doc and "/api/v1/" in doc and "TOTP" in doc


# --------------------------------------------------------------------------- F8 responsive

@pytest.mark.e2e
@pytest.mark.responsive
@goal("G-F8")
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
@goal("G-E2E")
def test_e2e_owner_journey(page, live_server, e2e_user, tmp_path, real_git, isolated_vault):
    """2FA login → this week → bot capture → API task → Obsidian edit → editor → agent apply/revert → search."""
    raise NotImplementedError("written in Round 5 when the pieces above exist (one test, the whole path)")
