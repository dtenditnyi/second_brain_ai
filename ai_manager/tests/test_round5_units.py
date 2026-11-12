"""Round 5 unit / integration tests for the risky parts (PROMPT_LEAN §3): Dataview sandbox,
render escaping, task toggle, attachments, weekly naming, 2FA, PWA cache, user isolation."""
import datetime
import json
import time

import pyotp
import pytest
from django.test import Client

from core import dataview, render, twofa, vault_index, weekly
from tests import vault_helpers as vh
from tests.acceptance.test_round4 import NOTE, post, real_git, remote, vclient, vuser  # noqa: F401


def notes_from(files):
    return [vault_index.parse_note(k, v) for k, v in files.items() if k.endswith(".md")]


FIX = notes_from(vh.FIXTURE_VAULT)


# --------------------------------------------------------------------------- Dataview-lite

@pytest.mark.parametrize("query", [
    'LIST FROM "../secret"', 'LIST FROM "/etc"', 'LIST FROM "C:/x"', 'LIST FROM ".git"',
    'TABLE x FROM "a\\b"', 'LIST FROM "01 - Projects/../../x"',
])
def test_dataview_from_cannot_leave_vault(query):
    assert dataview.run_on_notes(FIX, query)["kind"] == "error"


@pytest.mark.parametrize("query", [
    "dv.pages()", "```dataviewjs", "TABLE file.name GROUP BY status", "LIST FLATTEN tags",
    'LIST WHERE eval("1")', "TASK WHERE (", "", "CALENDAR file.ctime",
])
def test_dataview_unsupported_is_reported_not_run(query):
    assert dataview.run_on_notes(FIX, query)["kind"] == "unsupported"


def test_dataview_where_sort_limit_and_tasks():
    out = dataview.run_on_notes(FIX, 'TABLE WITHOUT ID file.name, status FROM #planning SORT file.name DESC LIMIT 2')
    assert out["columns"] == ["file.name", "status"] and len(out["rows"]) == 2
    names = [r["cells"][0] for r in out["rows"]]
    assert names == sorted(names, reverse=True)
    tasks = dataview.run_on_notes(FIX, 'TASK FROM "01 - Projects" WHERE completed')["rows"]
    assert tasks and all(t["status"] == "done" for t in tasks)
    dated = dataview.run_on_notes(FIX, 'LIST WHERE date >= date("2026-10-01")')["rows"]
    assert {r["name"] for r in dated} >= {"Second Brain", "Задачи"} and "Университет" not in {r["name"] for r in dated}
    assert dataview.run_on_notes(FIX, 'LIST WHERE contains(file.tags, "#dev")')["rows"][0]["name"] == "Second Brain"


def test_dataview_time_limit(monkeypatch):
    monkeypatch.setattr(dataview, "TIME_LIMIT", -1)
    assert dataview.run_on_notes(FIX, "LIST")["kind"] == "error"


# --------------------------------------------------------------------------- render

def test_render_escapes_raw_html_and_scripts_in_every_construct():
    text = ('<script>alert(1)</script>\n<img src=x onerror=alert(1)>\n'
            '> [!note] <b>x</b>\n> <iframe src=javascript:alert(1)>\n\n'
            '- [ ] <svg onload=alert(1)>\n[[<img src=x>|<script>]]\n$<img>$\n'
            '```mermaid\n<script>x</script>\n```\n')
    html = render.render_note(".", "a.md", text, FIX)["html"]
    for bad in ("<script", "<img src=x", "<iframe", "<svg", "<b>x</b>"):
        assert bad not in html, bad


def test_render_templater_not_executed_and_embed_depth_limited():
    files = {"a.md": "![[b]]\n<% tp.system.prompt() %>\n", "b.md": "![[a]]\nB\n"}
    html = render.render_note(".", "a.md", files["a.md"], notes_from(files))["html"]
    assert "tp.system.prompt" in html and "&lt;%" in html            # shown as text
    assert html.count("note-embed") < 6                                # no infinite recursion


def test_render_task_lines_point_at_file_lines():
    text = vh.FIXTURE_VAULT[NOTE]
    html = render.render_note(".", NOTE, text, FIX)["html"]
    lines = text.split("\n")
    import re
    for line_no, raw in re.findall(r'data-task-raw="([^"]*)"[^>]*data-task-line="(\d+)"', html) and [] or \
            [(m.group(2), m.group(1)) for m in re.finditer(r'data-task-raw="([^"]*)"[^>]*data-task-line="(\d+)"', html)]:
        assert lines[int(line_no)] == raw.replace("&gt;", ">")


# --------------------------------------------------------------------------- toggle-task / attachments

def test_toggle_task_conflict_when_line_changed(vclient, remote, tmp_path):
    vclient.get("/api/get-note/", {"path": NOTE})
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, NOTE, vh.FIXTURE_VAULT[NOTE].replace("- [/] Round 3", "- [/] Round 3 (renamed)"))
    r = post(vclient, "/api/notes/toggle-task/", {"path": NOTE, "line": "- [/] Round 3", "status": "done"})
    assert r.status_code == 409
    assert "- [/] Round 3 (renamed)" in vh.remote_file(remote, NOTE, tmp_path)


def test_toggle_task_rejects_non_task_and_bad_path(vclient):
    assert post(vclient, "/api/notes/toggle-task/", {"path": NOTE, "line": "# 🚀 Second Brain", "status": "done"}).status_code == 400
    assert post(vclient, "/api/notes/toggle-task/", {"path": "../x.md", "line": "- [ ] a", "status": "done"}).status_code == 400
    assert post(vclient, "/api/notes/toggle-task/", {"path": NOTE, "line": "- [ ] a", "status": "evil"}).status_code == 400


def test_attachments_served_from_cache_with_safe_headers(vclient, remote, tmp_path):
    phone = vh.clone(remote, tmp_path / "phone")
    (phone / "99 - Cache").mkdir()
    (phone / "99 - Cache" / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\nxx")
    (phone / "99 - Cache" / "page.html").write_bytes(b"<script>alert(1)</script>")
    vh.git(phone, "add", "-A"), vh.git(phone, "commit", "-m", "att"), vh.git(phone, "push", "origin", "HEAD:main")
    vclient.get("/api/get-note/", {"path": NOTE})
    r = vclient.get("/attachments/", {"name": "pic.png"})
    assert r.status_code == 200 and r["Content-Type"] == "image/png" and r["X-Content-Type-Options"] == "nosniff"
    html = vclient.get("/attachments/", {"name": "page.html"})
    assert html["Content-Type"] == "application/octet-stream" and "attachment" in html["Content-Disposition"]
    for bad in ({"name": "../db.sqlite3"}, {"name": "a/b.png"}, {"path": "/etc/passwd"}, {"path": "C:/Windows/win.ini"},
                {"path": ".obsidian/app.json"}, {"path": NOTE}):
        assert vclient.get("/attachments/", bad).status_code in (400, 404), bad


def test_other_users_cannot_read_my_vault(vclient, vuser, other_user, remote, tmp_path):
    vclient.get("/api/get-note/", {"path": NOTE})                    # alice's clone exists
    bob = Client()
    bob.force_login(other_user)
    assert bob.get("/api/get-note/", {"path": NOTE}).status_code == 404
    for url, key in (("/api/notes/search/?q=Аудит", "results"), ("/api/notes/graph/", "nodes")):
        r = bob.get(url)                         # bob has no vault: an error or nothing — never alice's notes
        assert r.status_code != 200 or r.json()[key] == []
        assert "Second Brain" not in r.content.decode()
    assert bob.get("/attachments/", {"path": NOTE}).status_code == 404
    assert Client().get("/api/notes/search/", {"q": "x"}).status_code == 302          # anonymous


# --------------------------------------------------------------------------- weekly

@pytest.mark.parametrize("prev, ahead, expected", [
    ("Fifth week of 2nd year", 2, "Seventh week of 2nd year"),
    ("Nineteenth week of 2nd year", 3, "22nd week of 2nd year"),
    ("Week 5", 1, "Week 6"),
    ("5th week of semester", 1, "6th week of semester"),
    ("Неделя 9 (B)", 1, "Неделя 10 (B)"),
])
def test_weekly_next_name(prev, ahead, expected):
    assert weekly.next_name(prev, ahead) == expected


def test_weekly_carry_over_is_idempotent_and_keeps_text(vclient, remote, tmp_path):
    week = post(vclient, "/api/weekly/this-week/", {"today": "2026-11-11"}).json()["path"]
    assert week.endswith("Seventh week of 2nd year.md")
    post(vclient, "/api/weekly/carry-over/", {"to": week})
    again = post(vclient, "/api/weekly/carry-over/", {"to": week}).json()
    assert again["count"] == 0
    new = vh.remote_file(remote, week, tmp_path)
    assert new.count("Повторить DSA") == 1 and "type: weekly" in new and "date: 2026-11-09" in new


# --------------------------------------------------------------------------- 2FA

def test_totp_replay_and_backup_code_single_use(vuser):
    s = vuser.settings
    secret = twofa.new_secret()
    codes, hashes = twofa.new_backup_codes()
    s.totp_enabled, s.totp_secret, s.totp_backup_codes = True, secret, hashes
    s.save()
    code = pyotp.TOTP(secret).now()
    assert twofa.verify(s, code) is True
    assert twofa.verify(s, code) is False                                      # replay of the same step
    assert twofa.verify(s, codes[0].upper().replace("-", " ")) is True         # tolerant format
    assert twofa.verify(s, codes[0]) is False                                  # used once
    s.refresh_from_db()
    assert s.totp_secret == secret and len(s.totp_backup_codes) == 9
    from django.db import connection
    with connection.cursor() as cur:
        cur.execute("SELECT totp_secret FROM core_usersettings WHERE id = %s", [s.pk])
        stored = cur.fetchone()[0]
    assert stored != secret and stored.startswith("gAAAAA")                    # encrypted at rest


def test_login_second_step_limits_and_expiry(vuser, settings):
    s = vuser.settings
    s.totp_enabled, s.totp_secret = True, twofa.new_secret()
    s.save()
    c = Client()
    c.post("/login/", {"username": vuser.username, "password": "Str0ng-Pass-123!", "next": "/tasks/"})
    for _ in range(5):
        c.post("/login/2fa/", {"code": "000000"})
    assert c.get("/login/2fa/").status_code == 302                             # back to the password step
    assert c.get("/").status_code == 302
    c.post("/login/", {"username": vuser.username, "password": "Str0ng-Pass-123!", "next": "https://evil.example/"})
    session = c.session
    session["sb_2fa_pending"]["at"] -= 3600
    session.save()
    assert c.get("/login/2fa/")["Location"].endswith("/login/")


def test_2fa_setup_needs_login_and_enable_needs_valid_code(vclient):
    assert Client().get("/api/2fa/setup/").status_code == 302
    assert post(vclient, "/api/2fa/enable/", {"code": "123456"}).status_code == 400   # no setup yet
    vclient.get("/api/2fa/setup/")
    assert post(vclient, "/api/2fa/enable/", {"code": "12"}).status_code == 400


# --------------------------------------------------------------------------- PWA

def test_sw_never_caches_writes_and_clears_on_message(client):
    body = client.get("/sw.js").content.decode()
    assert "request.method !== 'GET'" in body and "sb-clear-cache" in body and "response.redirected" in body
    assert "__STATIC__" not in body


def test_capture_session_endpoint_dedupes_client_id(vclient, remote, tmp_path, settings):
    one = post(vclient, "/api/capture/", {"text": "один раз", "client_id": "abc-1"})
    two = post(vclient, "/api/capture/", {"text": "один раз", "client_id": "abc-1"})
    assert one.status_code == two.status_code == 200 and two.json().get("duplicate")
    assert vh.remote_file(remote, settings.CAPTURE_INBOX_NOTE, tmp_path).count("один раз") == 1
    assert post(vclient, "/api/capture/", {"text": "  "}).status_code == 422


# --------------------------------------------------------------------------- symlinks never leak outside the vault

def test_index_skips_symlinks_leaving_the_vault(tmp_path):
    import os
    from core import notes_service
    outside = tmp_path / "other_user_vault"
    outside.mkdir()
    (outside / "secret.md").write_text("чужой секрет", encoding="utf-8")
    root = tmp_path / "vault"
    (root / "notes").mkdir(parents=True)
    (root / "notes" / "own.md").write_text("своё", encoding="utf-8")
    try:
        os.symlink(outside / "secret.md", root / "notes" / "leak.md")
        os.symlink(outside, root / "linkdir", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")
    rels = [rel for rel, _ in notes_service._walk_md(root)]
    assert rels == ["notes/own.md"]
    assert all("чужой" not in n.text for n in vault_index.scan_root(root))


def test_rag_loader_and_get_note_skip_symlinks(tmp_path, vclient, settings):
    import os
    from core import rag_engine
    from core.paths import get_user_paths
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("чужой секрет", encoding="utf-8")
    vault = tmp_path / "v"
    vault.mkdir()
    (vault / "own.md").write_text("своё", encoding="utf-8")
    try:
        os.symlink(outside / "secret.md", vault / "leak.md")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(rag_engine, "SimpleDirectoryReader",
                   lambda input_files: type("R", (), {"load_data": lambda self: list(input_files)})())
        assert [os.path.basename(f) for f in rag_engine._vault_documents(vault)] == ["own.md"]
    user = vclient.session.get("_auth_user_id")
    from django.contrib.auth.models import User
    root = get_user_paths(User.objects.get(pk=user))["notes_dir"]
    vclient.get("/api/get-note/", {"path": NOTE})            # make sure the clone exists
    os.symlink(outside / "secret.md", os.path.join(root, "leak.md"))
    r = vclient.get("/api/get-note/", {"name": "leak"})
    assert r.status_code == 404 and "чужой" not in r.content.decode()


def test_logout_header_and_login_page_both_clear_offline_cache(auth_client):
    r = auth_client.post("/logout/")
    assert r["Clear-Site-Data"] == '"cache"'
    assert 'id="sb-clear-cache"' in Client().get("/login/").content.decode()


# --------------------------------------------------------------------------- R4.5 LOW leftovers (data loss / duplicates)

def _offline(monkeypatch):
    from core import vault_writer
    real = vault_writer.VaultRepo.pull
    monkeypatch.setattr(vault_writer.VaultRepo, "pull",
                        lambda self: (_ for _ in ()).throw(vault_writer.VaultError("offline", "no network")))
    return lambda: monkeypatch.setattr(vault_writer.VaultRepo, "pull", real)


def test_chained_offline_saves_of_one_note_apply_in_order(vuser, remote, tmp_path, monkeypatch):
    from core import notes_service
    raw = notes_service.read_note(vuser, NOTE)
    online = _offline(monkeypatch)
    first = notes_service.save_note(vuser, NOTE, raw["content"] + "\nправка 1\n", raw["sha"])
    second = notes_service.save_note(vuser, NOTE, raw["content"] + "\nправка 1\nправка 2\n", first["sha"])
    assert first["queued"] and second["queued"]
    online()
    # back online, the editor saves again with the sha it got from the queued save
    third = notes_service.save_note(vuser, NOTE, raw["content"] + "\nправка 1\nправка 2\nправка 3\n", second["sha"])
    assert third["queued"] is False
    assert vh.remote_file(remote, NOTE, tmp_path).endswith("правка 1\nправка 2\nправка 3\n")
    files = vh.git(remote, "ls-tree", "-r", "--name-only", "main").stdout.splitlines()
    assert not [p for p in files if "конфликт" in p]


def test_two_conflict_copies_in_one_minute_do_not_block_outbox(vuser, remote, tmp_path, monkeypatch):
    from core import notes_service
    from core.models import VaultOutbox
    raw = notes_service.read_note(vuser, NOTE)
    online = _offline(monkeypatch)
    notes_service.save_note(vuser, NOTE, raw["content"] + "\nА\n", raw["sha"])
    VaultOutbox.objects.create(user=vuser, kind="note", op={"op": "save", "path": NOTE, "content": "Б\n",
                                                            "base_sha": raw["sha"]})
    online()
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, NOTE, raw["content"] + "\nс телефона\n")
    assert notes_service.flush_outbox(vuser) is True
    assert not VaultOutbox.objects.filter(user=vuser).exists()
    vh.git(phone, "fetch")
    copies = [p for p in vh.git(phone, "ls-tree", "-r", "--name-only", "origin/main").stdout.splitlines() if "конфликт" in p]
    texts = {vh.remote_file(remote, c, tmp_path).strip() for c in copies}
    assert len(copies) == 2 and any(t.endswith("А") for t in texts) and "Б" in texts


def test_resent_save_after_lost_response_is_not_a_conflict(vuser, remote, tmp_path):
    from core import notes_service
    raw = notes_service.read_note(vuser, NOTE)
    new = raw["content"] + "\nдошло\n"
    notes_service.save_note(vuser, NOTE, new, raw["sha"])
    again = notes_service.save_note(vuser, NOTE, new, raw["sha"])          # same request, old base
    assert again["sha"] == notes_service.sha(new)


def test_web_delete_and_rename_refuse_a_changed_note(vclient, remote, tmp_path):
    raw = vclient.get("/api/notes/raw/", {"path": NOTE}).json()
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, NOTE, raw["content"] + "\nс телефона\n")
    assert post(vclient, "/api/notes/delete/", {"path": NOTE, "base_sha": raw["sha"]}).status_code == 409
    r = post(vclient, "/api/notes/rename/", {"path": NOTE, "new_path": "01 - Projects/Новое.md", "base_sha": raw["sha"]})
    assert r.status_code == 409
    assert "с телефона" in vh.remote_file(remote, NOTE, tmp_path)
