"""Round 3 acceptance tests (docs/audit/round3/GOALS.md).

Every test names its goal. All goals are implemented: the strict expected-failure
markers used while building Round 3 are gone (start state: docs/audit/round3/acceptance-start.txt).
External services are never contacted: git runs against local bare repos.
"""
import datetime
import os
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from unittest import mock

import pytest
from django.conf import settings as dj_settings
from django.core.management import call_command
from django.test import Client

from tests import vault_helpers as vh
from tests.conftest import PASSWORD

ROOT = Path(__file__).resolve().parents[3]          # repository root
APP = ROOT / "ai_manager"


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

@pytest.fixture
def real_git(monkeypatch):
    """Undo the conftest network guard: these tests use local repos only."""
    import git
    from core import git_sync, vault_writer
    monkeypatch.setattr(git_sync, "Repo", git.Repo)
    monkeypatch.setattr(vault_writer, "Repo", git.Repo)


@pytest.fixture
def remote(tmp_path):
    return vh.make_remote(tmp_path)


@pytest.fixture
def vault_user(db, user, remote, real_git, isolated_vault):
    s = user.settings
    s.github_repo_url = str(remote)   # local path: no token, no network
    s.github_token = ""
    s.save()
    return user


# --------------------------------------------------------------------------
# G-A1 Markdown in AI answers
# --------------------------------------------------------------------------

def test_a1_markdown_libraries_are_local_and_loaded():
    for name in ("marked.min.js", "purify.min.js", "highlight.min.js"):
        assert (APP / "static" / "vendor" / name).is_file()
    for tpl in ("ai-chat.html", "home.html"):
        html = (APP / "templates" / tpl).read_text(encoding="utf-8")
        assert "vendor/purify.min.js" in html and "js/markdown.js" in html
        assert "cdn." not in html and "unpkg" not in html


def test_a1_history_is_rendered_from_raw_markdown(auth_client, user):
    from core.models import ChatMessage
    ChatMessage.objects.create(user=user, role="ai", content="# Title\n\n**bold** and `code`")
    html = auth_client.get("/chat/").content.decode()
    # The raw Markdown is shipped as text for the same client renderer (no |linebreaksbr HTML).
    assert 'data-markdown' in html and "# Title" in html


@pytest.mark.e2e
def test_a1_markdown_features_render_in_chat(logged_page, live_server):
    md = ("# Заголовок\n\n- пункт **жирный** *курсив*\n- [ ] задача\n- [x] готово\n\n"
          "| A | B |\n|---|---|\n| 1 | 2 |\n\n```python\nprint('hi')\n```\n\n"
          "Inline `x = 1` и [ссылка](https://example.com).\n\n> цитата\n\n"
          "> [!info] Инфо\n> текст callout\n\nСм. [[Университет]].")
    p = logged_page
    with mock.patch("core.rag_engine.ask_second_brain", return_value=md):
        p.goto(f"{live_server.url}/chat/")
        p.fill("#chat-input", "покажи")
        p.keyboard.press("Enter")
        bubble = p.locator(".chat-bubble .markdown-body").last
        bubble.locator("table").wait_for()
    assert bubble.locator("h1").inner_text() == "Заголовок"
    assert bubble.locator("strong").first.inner_text() == "жирный"
    assert bubble.locator("pre code.hljs").count() == 1
    assert bubble.locator("button.copy-code").count() == 1
    assert bubble.locator("blockquote").count() >= 1
    assert bubble.locator(".callout.callout-info").count() == 1
    assert bubble.locator("input[type=checkbox]").count() == 2
    link = bubble.locator("a[href='https://example.com']")
    assert link.get_attribute("target") == "_blank" and "noopener" in link.get_attribute("rel")
    wiki = bubble.locator("a.wiki-link")
    assert "/notes/?file=" in wiki.get_attribute("href") and "Университет" in wiki.inner_text()


@pytest.mark.e2e
@pytest.mark.parametrize("payload", [
    "<script>window.__xss=1</script>",
    '<img src=x onerror="window.__xss=2">',
    "[click](javascript:window.__xss=3)",
    '<svg><script>window.__xss=4</script></svg>',
    '<svg onload="window.__xss=5"></svg>',
    "```html\n<img src=x onerror=window.__xss=6>\n```",
    '<a href="javascript:window.__xss=7">x</a>',
])
def test_a1_markdown_is_sanitized(logged_page, live_server, payload):
    p = logged_page
    with mock.patch("core.rag_engine.ask_second_brain", return_value=f"Ответ:\n\n{payload}"):
        p.goto(f"{live_server.url}/chat/")
        p.fill("#chat-input", "x")
        p.keyboard.press("Enter")
        p.locator(".chat-bubble .markdown-body").last.wait_for()
        p.wait_for_timeout(400)
    assert p.evaluate("window.__xss") is None
    # No element may carry a javascript: URL or an inline handler (escaped text is harmless, see D20).
    bad = p.evaluate("""() => [...document.querySelectorAll('#chat-feed *')].filter(e =>
        [...e.attributes].some(a => /^on/i.test(a.name) || /^\s*javascript:/i.test(a.value))).map(e => e.outerHTML)""")
    assert bad == []
    assert p.locator("#chat-feed svg, #chat-feed script").count() == 0


@pytest.mark.e2e
def test_a1_history_and_new_answer_render_identically(logged_page, live_server, e2e_user):
    from core.models import ChatMessage
    md = "## Список\n\n1. один\n2. два\n\n`код`"
    ChatMessage.objects.create(user=e2e_user, role="ai", content=md)
    p = logged_page
    with mock.patch("core.rag_engine.ask_second_brain", return_value=md):
        p.goto(f"{live_server.url}/chat/")
        p.fill("#chat-input", "again")
        p.keyboard.press("Enter")
        p.locator(".chat-bubble .markdown-body").nth(1).wait_for()
    bodies = p.locator(".chat-bubble .markdown-body")
    first, last = bodies.first.inner_html(), bodies.last.inner_html()
    assert first == last and "<h2" in first and "<ol>" in first


@pytest.mark.e2e
def test_a1_status_report_renders_markdown(logged_page, live_server):
    p = logged_page
    with mock.patch("core.rag_engine.ask_second_brain", return_value="**Отлично** — 2 задачи\n\n- a\n- b"):
        p.reload()
        p.click("#generate-report-btn")
        p.locator("#ai-report-output strong").wait_for()
    assert p.locator("#ai-report-output li").count() == 2


@pytest.mark.e2e
def test_a1_wide_markdown_does_not_overflow_at_320(browser, live_server, e2e_user):
    from core.models import ChatMessage
    from tests.e2e.conftest import login
    wide = "| " + " | ".join(f"колонка {i}" for i in range(12)) + " |\n|" + "---|" * 12 + "\n| " + " | ".join("x" * 30 for _ in range(12)) + " |\n\n```\n" + "y" * 400 + "\n```"
    ChatMessage.objects.create(user=e2e_user, role="ai", content=wide)
    ctx = browser.new_context(viewport={"width": 320, "height": 640})
    page = ctx.new_page()
    try:
        login(page, live_server, "e2e")
        page.goto(f"{live_server.url}/chat/")
        page.locator(".chat-bubble .markdown-body table").wait_for()
        assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")
        assert page.evaluate("document.querySelector('.chat-bubble').getBoundingClientRect().right <= 320")
    finally:
        ctx.close()


# --------------------------------------------------------------------------
# G-A2 / G-A3 Core Matrix on tablets + themes
# --------------------------------------------------------------------------

@pytest.mark.e2e
@pytest.mark.responsive
@pytest.mark.parametrize("width", [768, 834, 1024, 1279])
def test_a2_core_matrix_no_horizontal_scroll_on_tablets(browser, live_server, e2e_admin, e2e_user, width):
    from core.models import Task
    from tests.e2e.conftest import login
    for i in range(3):
        Task.objects.create(user=e2e_user, title=f"Long admin task title number {i} " * 3, tags="dev")
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    page = ctx.new_page()
    try:
        login(page, live_server, "e2eroot")
        for tab in ("users-table", "settings-table", "tasks-table", "messages-table"):
            page.goto(f"{live_server.url}/system-matrix/")
            page.click(f'[data-tab="{tab}"]')
            scroll = page.evaluate(f"""() => {{ const w = document.querySelector('#{tab} table').parentElement;
                return [w.scrollWidth, w.clientWidth, document.documentElement.scrollWidth, innerWidth]; }}""")
            assert scroll[0] <= scroll[1] + 1 and scroll[2] <= scroll[3], (tab, scroll)
    finally:
        ctx.close()


@pytest.mark.e2e
@pytest.mark.responsive
# already satisfied (guard): must stay a table from 1280 px
def test_a2_core_matrix_is_a_table_from_1280(browser, live_server, e2e_admin):
    from tests.e2e.conftest import login
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    try:
        login(page, live_server, "e2eroot")
        page.goto(f"{live_server.url}/system-matrix/")
        assert page.evaluate("getComputedStyle(document.querySelector('#users-table thead')).display") == "table-header-group"
    finally:
        ctx.close()


def test_a3_core_matrix_uses_user_theme(admin_client_, superuser):
    from core.models import UserSettings
    UserSettings.objects.filter(user=superuser).update(theme="light", accent_color="green")
    html = admin_client_.get("/system-matrix/").content.decode()
    assert 'data-theme="light"' in html and 'data-accent="green"' in html
    assert "bg-[#07070a]" not in html and "text-white" not in html


@pytest.mark.e2e
@pytest.mark.responsive
# passes today only because the page ignores the theme; must keep passing once it follows it
@pytest.mark.parametrize("theme", ["light", "cyberpunk"])
def test_a3_core_matrix_contrast_aa(browser, live_server, e2e_admin, theme):
    from core.models import UserSettings
    from tests.e2e.conftest import login
    from tests.e2e.test_responsive_round2 import RENDERED_CONTRAST_JS
    UserSettings.objects.filter(user=e2e_admin).update(theme=theme, accent_color="purple")
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    page = ctx.new_page()
    try:
        login(page, live_server, "e2eroot")
        page.goto(f"{live_server.url}/system-matrix/")
        assert page.evaluate(RENDERED_CONTRAST_JS) == []
    finally:
        ctx.close()


# --------------------------------------------------------------------------
# G-A4 logs outside git, rotation
# --------------------------------------------------------------------------

def test_a4_logs_not_tracked_and_ignored():
    tracked = subprocess.run(["git", "ls-files", "ai_manager/logs"], cwd=ROOT, capture_output=True, text=True).stdout.split()
    assert tracked == ["ai_manager/logs/.gitkeep"], tracked
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "ai_manager/logs/*" in ignore and "!ai_manager/logs/.gitkeep" in ignore


def test_a4_size_based_rotation_and_dir_created(tmp_path):
    out = subprocess.run([sys.executable, "-c",
                          "import json; from django.conf import settings as s; import os;"
                          "print(json.dumps({k: [h['class'], h.get('maxBytes'), h.get('backupCount')] "
                          "for k, h in s.LOGGING['handlers'].items() if 'filename' in h}));"
                          "print(os.path.isdir(s.LOGS_DIR))"],
                         cwd=APP, env={**os.environ, "DJANGO_SETTINGS_MODULE": "ai_manager.settings_local",
                                       "LOG_DIR": str(tmp_path / "newlogs")},
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    handlers, created = out.stdout.strip().splitlines()[-2:]
    import json
    for cls, max_bytes, backups in json.loads(handlers).values():
        assert cls == "logging.handlers.RotatingFileHandler" and max_bytes and backups
    assert created == "True"


# --------------------------------------------------------------------------
# G-C1 format + docs
# --------------------------------------------------------------------------

def test_c1_tasks_format_document():
    doc = (ROOT / "docs" / "TASKS_FORMAT.md").read_text(encoding="utf-8")
    for needle in ("TASKS_NOTE_PATH", "01 - Projects/🎯 Цели и планы/Задачи.md", "🆔", "⏫", "🔼", "🔽",
                   "[/]", "[-]", "✅", "📥 Входящие", "type: tasks-db", "🔗 [[Главная (Home)]]"):
        assert needle in doc, needle


def test_c1_new_note_has_frontmatter_and_moc_link():
    from core import tasks_md
    text = tasks_md.new_tasks_note(datetime.date(2026, 11, 11))
    assert text.startswith("---\n") and "type: tasks-db" in text and "tags: [planning]" in text
    assert "aliases: [Задачи, Tasks]" in text and "date: 2026-11-11" in text and "status: active" in text
    assert "## 📥 Входящие" in text and text.rstrip().endswith("🔗 [[Главная (Home)]]")


def test_c1_settings_path_default_and_per_user(user):
    assert dj_settings.TASKS_NOTE_PATH == "01 - Projects/🎯 Цели и планы/Задачи.md"
    assert dj_settings.TASKS_SYNC_INTERVAL == 60
    from core.tasks_service import tasks_note_path
    assert tasks_note_path(user) == dj_settings.TASKS_NOTE_PATH
    s = user.settings
    s.tasks_note_path = "02 - Areas/Мои задачи.md"
    s.save()
    assert tasks_note_path(user) == "02 - Areas/Мои задачи.md"


def test_c1_line_format_is_tasks_plugin_compatible():
    from core import tasks_md
    text, info = tasks_md.apply_op("## 📥 Входящие\n", {"op": "add", "text": "Сдать лабу", "due": "2026-11-14",
                                                         "priority": "high", "tags": ["university"]},
                                   today=datetime.date(2026, 11, 11))
    line = [l for l in text.splitlines() if l.startswith("- [")][0]
    assert re.fullmatch(r"- \[ \] Сдать лабу 📅 2026-11-14 ⏫ #university ➕ 2026-11-11 🆔 [a-z0-9]{6}", line), line
    with pytest.raises(ValueError):
        tasks_md.apply_op(text, {"op": "add", "text": "x", "tags": ["not-allowed"]})


# --------------------------------------------------------------------------
# G-C2 lossless parser
# --------------------------------------------------------------------------

def test_c2_roundtrip_fixture_and_fields():
    from core import tasks_md
    src = vh.FIXTURE_VAULT[vh.TASKS_NOTE]
    note = tasks_md.parse(src)
    assert tasks_md.serialize(note) == src
    by_id = {t.id: t for t in note.tasks if t.id}
    t = by_id["t7k2m9"]
    assert (t.status, t.text, t.due, t.priority, t.tags, t.created) == (
        "todo", "Сдать лабу по физике", "2026-11-14", "high", ["university"], "2026-11-11")
    assert by_id["a1b2c3"].status == "in_progress" and "⏳ 2026-11-12" in by_id["a1b2c3"].extra
    assert by_id["zz9yy8"].status == "done" and by_id["zz9yy8"].done == "2026-11-05"
    sub = [x for x in note.tasks if x.text == "подзадача без ID"][0]
    assert sub.indent == "    " and sub.id is None


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_c2_roundtrip_crlf_and_untouched_bytes_after_edit(newline):
    from core import tasks_md
    src = vh.FIXTURE_VAULT[vh.TASKS_NOTE].replace("\n", newline)
    assert tasks_md.serialize(tasks_md.parse(src)) == src
    out, _ = tasks_md.apply_op(src, {"op": "update", "id": "t7k2m9", "status": "done"}, today=datetime.date(2026, 11, 12))
    changed = [(a, b) for a, b in zip(src.split(newline), out.split(newline)) if a != b]
    assert len(changed) == 1 and "- [x] Сдать лабу по физике" in changed[0][1] and "✅ 2026-11-12" in changed[0][1]
    assert out.count(newline) == src.count(newline)


def test_c2_ids_added_and_duplicates_fixed():
    from core import tasks_md
    src = "- [ ] a 🆔 dup111\n- [ ] b 🆔 dup111\n- [ ] c\n"
    out, info = tasks_md.apply_op(src, {"op": "ensure_ids"})
    ids = [t.id for t in tasks_md.parse(out).tasks]
    assert len(set(ids)) == 3 and ids[0] == "dup111" and all(ids)


def test_c2_property_roundtrip_hypothesis():
    from hypothesis import given, settings as hset, strategies as st
    from core import tasks_md
    alphabet = st.sampled_from(list("abc эюя🔥📅⏫🔼🔽🆔✅➕#[]x/- \t") + ["\n", "\r\n", "- [ ] ", "- [x] ", "    - [/] "])

    @hset(max_examples=300, deadline=None)
    @given(st.lists(alphabet, max_size=80).map("".join))
    def roundtrip(text):
        assert tasks_md.serialize(tasks_md.parse(text)) == text

    roundtrip()


# --------------------------------------------------------------------------
# G-C3 single write path
# --------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["../x.md", "/etc/passwd", "C:\\Windows\\x.md", ".git/config", ".obsidian/app.json",
                                 "a/../../x.md", "notes/./../../x.md", "", "dir/"])
def test_c3_unsafe_paths_rejected(tmp_path, bad):
    from core import vault_writer
    (tmp_path / "vault").mkdir()
    with pytest.raises(vault_writer.UnsafePath):
        vault_writer.safe_path(tmp_path / "vault", bad)


def test_c3_symlink_escape_rejected(tmp_path):
    from core import vault_writer
    vault = tmp_path / "vault"
    vault.mkdir()
    (tmp_path / "outside").mkdir()
    try:
        os.symlink(tmp_path / "outside", vault / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this machine")
    with pytest.raises(vault_writer.UnsafePath):
        vault_writer.safe_path(vault, "link/x.md")


def test_c3_add_task_commits_and_pushes_with_site_author(vault_user, remote, tmp_path):
    from core import tasks_service
    tasks_service.add_task(vault_user, text="Новая задача", priority="medium", tags=["dev"])
    note = vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    assert "- [ ] Новая задача 🔼 #dev" in note and "Личный текст владельца — не трогать." in note
    author, message = vh.remote_log(remote)[0]
    assert author == "Second Brain" and message.startswith("tasks:")


def test_c3_concurrent_push_is_retried_without_loss(vault_user, remote, tmp_path, monkeypatch):
    """The phone pushes between our pull and our push: the push is rejected, we pull and re-apply the OPERATION."""
    from core import tasks_service, vault_writer
    phone = vh.clone(remote, tmp_path / "phone")
    tasks_service.sync_tasks(vault_user, force=True)
    calls = {"n": 0}
    real_push = vault_writer.VaultRepo.push

    def push_after_phone(self):
        if calls["n"] == 0:
            vh.commit_and_push(phone, vh.TASKS_NOTE,
                               vh.FIXTURE_VAULT[vh.TASKS_NOTE].replace("## ✅ Выполнено\n", "## ✅ Выполнено\n- [ ] С телефона #personal\n"))
        calls["n"] += 1
        return real_push(self)

    monkeypatch.setattr(vault_writer.VaultRepo, "push", push_after_phone)
    tasks_service.add_task(vault_user, text="С сайта")
    note = vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    assert calls["n"] == 2
    assert note.count("С сайта") == 1 and note.count("С телефона") == 1


def test_c3_two_writers_in_parallel(vault_user, other_user, remote, tmp_path, monkeypatch):
    """Two site clones (e.g. two hosts) push at the same time; both operations survive.

    The threads run only the git write path (vault_apply): the in-memory SQLite
    test DB cannot take parallel writes from threads (Postgres in prod can) — D22.
    """
    from core import tasks_service, vault_writer
    s = other_user.settings
    s.github_repo_url = str(remote)
    s.save()
    errors = []
    barrier = threading.Barrier(2)
    real_push = vault_writer.VaultRepo.push

    first = threading.local()
    pushes = []

    def synchronised_push(self):
        if not getattr(first, "done", False):
            first.done = True
            try:
                barrier.wait(timeout=20)   # both commits ready → push at the same moment
            except threading.BrokenBarrierError:
                pass
        pushes.append(1)
        return real_push(self)

    monkeypatch.setattr(vault_writer.VaultRepo, "push", synchronised_push)

    def run(u, text):
        try:
            op = {"op": "add", "text": text, "id": tasks_service.tasks_md.generate_id([])}
            vault_writer.vault_apply(u, tasks_service._note_operation(u, [op]), f"tasks: add {text}")
        except Exception as e:  # pragma: no cover - reported below
            errors.append(e)

    threads = [threading.Thread(target=run, args=(vault_user, "Поток A")),
               threading.Thread(target=run, args=(other_user, "Поток B"))]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    note = vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    assert errors == [] and note.count("Поток A") == 1 and note.count("Поток B") == 1
    assert len(pushes) >= 3        # one of the two simultaneous pushes was rejected and retried


def test_c3_task_deleted_elsewhere_gives_clear_message(vault_user, remote, tmp_path):
    from core import tasks_service
    from core.models import Task
    tasks_service.sync_tasks(vault_user, force=True)
    task = Task.objects.get(user=vault_user, vault_id="t7k2m9")
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, vh.TASKS_NOTE, vh.FIXTURE_VAULT[vh.TASKS_NOTE].replace(
        "- [ ] Сдать лабу по физике 📅 2026-11-14 ⏫ #university ➕ 2026-11-11 🆔 t7k2m9\n", ""))
    with pytest.raises(tasks_service.TaskSyncError) as err:
        tasks_service.update_task(vault_user, task.pk, status="done")
    assert "удалена" in str(err.value).lower() or "deleted" in str(err.value).lower()
    assert not Task.objects.filter(pk=task.pk).exists()


def test_c3_no_write_permission_is_reported(vault_user, monkeypatch):
    from core import tasks_service, vault_writer
    tasks_service.sync_tasks(vault_user, force=True)

    def denied(self):
        raise vault_writer.VaultError("permission", "remote: Permission to x denied. 403")

    monkeypatch.setattr(vault_writer.VaultRepo, "push", denied)
    with pytest.raises(tasks_service.TaskSyncError) as err:
        tasks_service.add_task(vault_user, text="x")
    assert "Contents: Read and write" in str(err.value)
    vault_user.settings.refresh_from_db()
    assert "Contents: Read and write" in vault_user.settings.tasks_sync_error


def test_c3_git_sync_and_writer_share_the_lock(vault_user, tmp_path):
    from core import vault_writer
    from core.rag_engine import get_user_paths
    path = get_user_paths(vault_user)["notes_dir"]
    lock = vault_writer.vault_lock(path)
    with lock:
        held = vault_writer.vault_lock(path, timeout=0.2)
        with pytest.raises(vault_writer.VaultError):
            with held:
                pass


# --------------------------------------------------------------------------
# G-C4 cache + sync
# --------------------------------------------------------------------------

def test_c4_sync_builds_cache_from_note(vault_user):
    from core import tasks_service
    from core.models import Task
    tasks_service.sync_tasks(vault_user, force=True)
    tasks = {t.vault_id: t for t in Task.objects.filter(user=vault_user)}
    assert tasks["t7k2m9"].status == "todo" and str(tasks["t7k2m9"].due_date) == "2026-11-14"
    assert tasks["t7k2m9"].priority == "high" and tasks["t7k2m9"].tags == "university"
    assert tasks["a1b2c3"].status == "in_progress" and tasks["zz9yy8"].status == "done"
    assert Task.objects.filter(user=vault_user).count() == 5  # incl. sub-task and line without ID
    vault_user.settings.refresh_from_db()
    assert vault_user.settings.tasks_last_sync is not None


def test_c4_interval_respected_and_refresh_forces(vault_user, auth_client, remote, tmp_path):
    from core import tasks_service
    tasks_service.sync_tasks(vault_user, force=True)
    with mock.patch.object(tasks_service, "_sync_now", wraps=tasks_service._sync_now) as spy:
        auth_client.get("/tasks/")
        assert spy.call_count == 0  # synced < 60 s ago
        r = auth_client.post("/api/tasks/sync/")
        assert r.status_code == 200 and r.json()["status"] == "ok" and spy.call_count == 1


def test_c4_changes_from_obsidian_appear(vault_user, auth_client, remote, tmp_path):
    from core import tasks_service
    from core.models import Task
    tasks_service.sync_tasks(vault_user, force=True)
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, vh.TASKS_NOTE, vh.FIXTURE_VAULT[vh.TASKS_NOTE].replace("- [ ] Сдать лабу", "- [x] Сдать лабу"))
    auth_client.post("/api/tasks/sync/")
    assert Task.objects.get(user=vault_user, vault_id="t7k2m9").status == "done"


def test_c4_management_command_and_ui_show_last_sync(vault_user, auth_client):
    call_command("sync_tasks", "--all")
    vault_user.settings.refresh_from_db()
    assert vault_user.settings.tasks_last_sync
    html = auth_client.get("/tasks/").content.decode()
    assert 'id="tasks-last-sync"' in html and 'id="tasks-refresh"' in html


# --------------------------------------------------------------------------
# G-C5 offline outbox
# --------------------------------------------------------------------------

def test_c5_offline_operations_are_queued_and_flushed_in_order(vault_user, remote, tmp_path, monkeypatch):
    from core import tasks_service, vault_writer
    from core.models import Task, VaultOutbox
    tasks_service.sync_tasks(vault_user, force=True)
    real_pull = vault_writer.VaultRepo.pull

    def offline(self):
        raise vault_writer.VaultError("offline", "Could not resolve host: github.com")

    monkeypatch.setattr(vault_writer.VaultRepo, "pull", offline)
    t1 = tasks_service.add_task(vault_user, text="Офлайн 1")
    t2 = tasks_service.add_task(vault_user, text="Офлайн 2")
    tasks_service.update_task(vault_user, t1.pk, status="in_progress")
    assert VaultOutbox.objects.filter(user=vault_user).count() == 3
    assert not Task.objects.get(pk=t1.pk).synced and Task.objects.get(pk=t1.pk).status == "in_progress"
    monkeypatch.setattr(vault_writer.VaultRepo, "pull", real_pull)
    tasks_service.sync_tasks(vault_user, force=True)
    note = vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    assert VaultOutbox.objects.filter(user=vault_user).count() == 0
    assert note.index("Офлайн 1") < note.index("Офлайн 2") and "- [/] Офлайн 1" in note
    assert all(t.synced for t in Task.objects.filter(user=vault_user))


def test_c5_unsynced_badge_in_ui(vault_user, auth_client, monkeypatch):
    from core import tasks_service, vault_writer
    tasks_service.sync_tasks(vault_user, force=True)
    monkeypatch.setattr(vault_writer.VaultRepo, "pull",
                        lambda self: (_ for _ in ()).throw(vault_writer.VaultError("offline", "no network")))
    tasks_service.add_task(vault_user, text="Пока не в git")
    assert "не синхронизировано" in auth_client.get("/tasks/").content.decode()


# --------------------------------------------------------------------------
# G-C6 export of old tasks
# --------------------------------------------------------------------------

def test_c6_export_dry_run_then_real_then_idempotent(vault_user, remote, tmp_path, capsys):
    from core.models import Task
    Task.objects.create(user=vault_user, title="Старая задача", priority="urgent", tags="dev", due_date="2026-12-01")
    Task.objects.create(user=vault_user, title="Старая готовая", status="done")
    before = vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    call_command("export_tasks_to_note", "--user", vault_user.username, "--dry-run")
    out = capsys.readouterr().out
    assert "Старая задача" in out and vh.remote_file(remote, vh.TASKS_NOTE, tmp_path) == before
    call_command("export_tasks_to_note", "--user", vault_user.username)
    call_command("export_tasks_to_note", "--user", vault_user.username)
    note = vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    assert note.count("Старая задача") == 1 and note.count("Старая готовая") == 1
    assert "- [x] Старая готовая" in note and "Личный текст владельца — не трогать." in note


# --------------------------------------------------------------------------
# G-C7 tasks UI
# --------------------------------------------------------------------------

def test_c7_api_edit_fields_and_delete(vault_user, auth_client, remote, tmp_path, post_json):
    from core import tasks_service
    from core.models import Task
    tasks_service.sync_tasks(vault_user, force=True)
    t = Task.objects.get(user=vault_user, vault_id="t7k2m9")
    r = post_json(auth_client, "/api/update-task/", {"task_id": t.pk, "title": "Лаба 2", "due_date": "2026-11-20",
                                                     "priority": "low", "tags": "university, physics", "status": "in_progress"})
    assert r.status_code == 200, r.content
    note = vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    assert "- [/] Лаба 2 📅 2026-11-20 🔽 #university #physics" in note and "🆔 t7k2m9" in note
    assert post_json(auth_client, "/api/delete-task/", {"task_id": t.pk}).status_code == 200
    assert "t7k2m9" not in vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)


def test_c7_each_user_has_own_note(vault_user, other_user, tmp_path, real_git):
    from core import tasks_service
    from core.models import Task
    other_remote = vh.make_remote(tmp_path, files={"README.md": "x\n"}, name="other.git")
    s = other_user.settings
    s.github_repo_url = str(other_remote)
    s.save()
    tasks_service.sync_tasks(vault_user, force=True)
    tasks_service.add_task(other_user, text="Только у Боба")
    assert Task.objects.filter(user=vault_user, title="Только у Боба").count() == 0
    note = vh.remote_file(other_remote, vh.TASKS_NOTE, tmp_path)
    assert "type: tasks-db" in note and "Только у Боба" in note
    assert "Только у Боба" not in vh.remote_file(vh.Path(tmp_path) / "remote.git", vh.TASKS_NOTE, tmp_path)


@pytest.mark.e2e
def test_c7_e2e_add_edit_delete_with_confirm(page, live_server, e2e_user, tmp_path, real_git, isolated_vault):
    from tests.e2e.conftest import login
    remote = vh.make_remote(tmp_path)
    s = e2e_user.settings
    s.github_repo_url = str(remote)
    s.save()
    login(page, live_server, "e2e")
    page.goto(f"{live_server.url}/tasks/")
    page.get_by_role("button", name=re.compile("Add New Task")).click()
    page.fill("#task-title", "E2E задача")
    page.select_option("#task-priority", "high")
    page.fill("#task-date", "2026-12-24")
    page.fill("#task-tags", "dev")
    with page.expect_navigation():
        page.get_by_role("button", name="Save Task").click()
    card = page.locator("article", has_text="E2E задача").first
    assert "dev" in card.inner_text()
    note = vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    assert "E2E задача 📅 2026-12-24 ⏫ #dev" in note
    card.get_by_role("button", name=re.compile("Edit")).click()
    page.fill("#task-title", "E2E задача (изм.)")
    with page.expect_navigation():
        page.get_by_role("button", name="Save Task").click()
    assert "E2E задача (изм.)" in vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    page.once("dialog", lambda d: d.accept())
    with page.expect_navigation():
        page.locator("article", has_text="E2E задача (изм.)").first.get_by_role("button", name=re.compile("Delete")).click()
    assert "E2E задача" not in vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)


@pytest.mark.e2e
@pytest.mark.responsive
@pytest.mark.parametrize("width,height", [(320, 568), (390, 844), (768, 1024), (1440, 900)])
def test_c7_tasks_page_responsive(browser, live_server, e2e_user, width, height):
    from core.models import Task
    from tests.e2e.conftest import login
    from tests.e2e.responsive_helpers import METRICS_JS
    Task.objects.create(user=e2e_user, title="Очень длинная задача " * 6, tags="dev, university", due_date="2026-12-01",
                        priority="urgent", vault_id="abc123", synced=False)
    ctx = browser.new_context(viewport={"width": width, "height": height})
    page = ctx.new_page()
    try:
        login(page, live_server, "e2e")
        page.goto(f"{live_server.url}/tasks/")
        m = page.evaluate(METRICS_JS)
        assert m["docScroll"] <= m["vw"] and m["overflowing"] == []
        if width < 1024:
            assert m["smallTargets"] == [], m["smallTargets"]
    finally:
        ctx.close()


# --------------------------------------------------------------------------
# G-B1 production config
# --------------------------------------------------------------------------

def test_b1_dockerfile_multistage_nonroot_no_node_in_final():
    df = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    stages = re.split(r"(?m)^FROM ", df)
    assert len(stages) >= 3, "multi-stage"
    final = stages[-1]
    assert "npm" not in final and "gcc" not in final and "nodejs" not in final
    assert re.search(r"(?m)^USER (?!root)\w+", final)
    assert "PYTHONDONTWRITEBYTECODE" in df and "PYTHONUNBUFFERED" in df and "git" in final
    assert "npm run build" in df or "tailwindcss" in df
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for item in ("venv", "node_modules", "*.sqlite3", "logs", ".env", ".git", "chroma_db", "obsidian_data",
                 "docs/audit/responsive", "cloudflared.exe"):
        assert item in ignore, item


def test_b1_compose_services_restart_health_volumes_no_public_ports():
    import yaml
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    assert "tailwind" not in services
    for name in ("db", "web", "scheduler", "tunnel"):
        assert services[name]["restart"] == "unless-stopped", name
        assert "logging" in services[name], name
    assert "healthz" in str(services["web"]["healthcheck"]["test"])
    assert "pg_isready" in str(services["db"]["healthcheck"]["test"])
    assert services["web"]["depends_on"]["db"]["condition"] == "service_healthy"
    assert "ports" not in services["db"]
    for port in services["web"].get("ports", []):
        assert str(port).startswith("${WEB_BIND") or str(port).startswith("127.0.0.1"), port
    vols = set(compose["volumes"])
    assert {"postgres_data", "chroma_db", "obsidian_data", "hf_cache", "app_logs", "staticfiles"} <= vols
    assert "sync_tasks" in str(services["scheduler"]["command"]) + str(services["scheduler"].get("entrypoint", ""))
    assert "Europe/Bucharest" in str(compose)


def test_b1_entrypoint_waits_for_db_migrates_collects():
    ep = (ROOT / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert ep.startswith("#!/") and "set -euo pipefail" in ep
    for needle in ("migrate --noinput", "collectstatic --noinput", "gunicorn", "GUNICORN_WORKERS:-2", "GUNICORN_TIMEOUT:-300"):
        assert needle in ep, needle
    assert ep.index("migrate") < ep.index("collectstatic") < ep.index("gunicorn")


def test_b1_healthz_ok_without_login_and_db_checked(client, db):
    r = client.get("/healthz/")
    assert r.status_code == 200 and r.json() == {"status": "ok", "db": "ok"}
    with mock.patch("core.views.health.connection") as conn:
        conn.cursor.side_effect = Exception("db down")
        r = client.get("/healthz/")
    assert r.status_code == 503 and r.json()["db"] == "error"


def _prod_settings(env):
    base = {k: v for k, v in os.environ.items() if not k.startswith("SECONDBRAIN_")}
    return subprocess.run([sys.executable, "-c", "from django.conf import settings as s; s.DEBUG; "
                           "print(s.ALLOWED_HOSTS, s.CSRF_TRUSTED_ORIGINS, s.SESSION_COOKIE_SECURE, s.SECURE_HSTS_SECONDS)"],
                          cwd=APP, env={**base, "DJANGO_SETTINGS_MODULE": "ai_manager.settings", **env},
                          capture_output=True, text=True, timeout=120)


@pytest.mark.parametrize("key", ["", "default-insecure-key-for-dev"])
def test_b1_insecure_secret_key_refused_in_production(key):
    out = _prod_settings({"DEBUG": "False", "SECRET_KEY": key})
    assert out.returncode != 0 and "SECRET_KEY" in out.stderr


def test_b1_hosts_and_origins_from_env():
    out = _prod_settings({"DEBUG": "False", "SECRET_KEY": "x" * 60, "ALLOWED_HOSTS": "a.example,b.example",
                          "CSRF_TRUSTED_ORIGINS": "https://a.example"})
    assert out.returncode == 0, out.stderr
    assert "['a.example', 'b.example'] ['https://a.example'] True" in out.stdout
    default = _prod_settings({"DEBUG": "False", "SECRET_KEY": "x" * 60})
    assert "secondbrain-core.com" in default.stdout


def test_b1_check_deploy_has_no_warnings():
    # Test-runner-only variables (conftest sets DJANGO_ALLOW_ASYNC_UNSAFE for Playwright) are not deployment.
    env = {k: v for k, v in os.environ.items() if not k.startswith("SECONDBRAIN_") and k != "DJANGO_ALLOW_ASYNC_UNSAFE"}
    env.update({"DJANGO_SETTINGS_MODULE": "ai_manager.settings", "DEBUG": "False",
                "SECRET_KEY": "Zq7-Lm2pR9vXc4Tn8Hb1Wd6Ks3Fy0Gj5Ae-Uo2Ri7Pt9Nl4Sx1Vc8Bm3Dh6Qw0",
                "DB_ENGINE": "sqlite"})
    out = subprocess.run([sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
                         cwd=APP, env=env, capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stdout + out.stderr


def test_b1_env_example_lists_all_variables():
    ex = (ROOT / ".env.example").read_text(encoding="utf-8")
    for var in ("SECRET_KEY", "DEBUG", "ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS", "POSTGRES_PASSWORD", "OLLAMA_HOST",
                "GEMINI_API_KEY", "TASKS_NOTE_PATH", "TASKS_SYNC_INTERVAL", "GUNICORN_WORKERS", "GUNICORN_TIMEOUT",
                "CLOUDFLARE_TUNNEL_TOKEN", "WEB_BIND", "TZ", "LOG_DIR"):
        assert re.search(rf"(?m)^#?\s*{var}=", ex), var


# already satisfied before Round 3 (guard) — see GOALS.md
def test_b1_auto_hybrid_uses_gemini_when_lan_pc_is_off(configured_user_r3, monkeypatch, settings):
    """OLLAMA_HOST on another PC in the LAN; the PC is off → Gemini answers."""
    from llama_index.core.llms import MockLLM
    from core import rag_engine
    settings.OLLAMA_HOST = "http://192.0.2.10:11434"
    seen = {}

    def fake_get(url, timeout):
        seen["url"] = url
        import requests
        raise requests.exceptions.ConnectTimeout()

    monkeypatch.setattr(rag_engine.requests, "get", fake_get)
    monkeypatch.setattr(rag_engine, "GoogleGenAI", lambda **kw: MockLLM())
    monkeypatch.setattr(rag_engine, "Ollama", lambda **kw: (_ for _ in ()).throw(AssertionError("PC is off")))
    out = rag_engine.ask_second_brain("q", configured_user_r3)
    assert seen["url"].startswith("http://192.0.2.10:11434") and not out.startswith("System Error")


@pytest.fixture
def configured_user_r3(user, note_writer, monkeypatch):
    from core import rag_engine
    s = user.settings
    s.github_repo_url, s.ai_strategy = "https://github.com/u/v.git", "auto"
    s.save()
    note_writer(user, "A", "alpha")
    monkeypatch.setattr(rag_engine, "sync_obsidian_repo", lambda *a, **k: True)
    return user


# --------------------------------------------------------------------------
# G-B2 deploy scripts
# --------------------------------------------------------------------------

SCRIPTS = ["install.sh", "update.sh", "backup.sh", "restore.sh", "status.sh", "migrate-from-old-pc.sh"]


def _bash():
    for candidate in (shutil.which("bash"), r"C:\Program Files\Git\bin\bash.exe"):
        if candidate and Path(candidate).exists():
            return candidate
    pytest.skip("bash not available")


@pytest.mark.parametrize("script", SCRIPTS)
def test_b2_scripts_strict_mode_and_bash_syntax(script):
    path = ROOT / "deploy" / script
    text = path.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash") and "set -euo pipefail" in text
    assert "\r\n" not in text
    out = subprocess.run([_bash(), "-n", str(path)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def test_b2_shellcheck_clean():
    exe = Path(sys.executable).parent / ("shellcheck.exe" if os.name == "nt" else "shellcheck")
    if not exe.exists():
        exe = Path(shutil.which("shellcheck") or "")
    if not exe.is_file():
        pytest.skip("shellcheck not installed (pip install shellcheck-py)")
    out = subprocess.run([str(exe), "-S", "warning", *[str(ROOT / "deploy" / s) for s in SCRIPTS]],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr


def test_b2_script_contents():
    d = ROOT / "deploy"
    install = (d / "install.sh").read_text(encoding="utf-8")
    assert "download.docker.com" in install and "docker-compose-plugin" in install and "usermod -aG docker" in install
    assert "secondbrain.service" in install and "secondbrain-backup.timer" in install
    update = (d / "update.sh").read_text(encoding="utf-8")
    assert "git pull" in update and "backup.sh" in update and "healthz" in update and "rollback" in update.lower()
    backup = (d / "backup.sh").read_text(encoding="utf-8")
    assert "pg_dump" in backup and "gzip" in backup and "14" in backup and "--with-files" in backup
    restore = (d / "restore.sh").read_text(encoding="utf-8")
    assert "read -r" in restore and "psql" in restore
    status = (d / "status.sh").read_text(encoding="utf-8")
    for needle in ("docker compose", "healthz", "df -h", "backups", "sync_tasks"):
        assert needle in status, needle
    svc = (d / "systemd" / "secondbrain.service").read_text(encoding="utf-8")
    assert "docker compose" in svc and "WantedBy=multi-user.target" in svc
    timer = (d / "systemd" / "secondbrain-backup.timer").read_text(encoding="utf-8")
    assert "03:30" in timer and "Persistent=true" in timer


def test_b2_install_never_prints_env_values():
    install = (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")
    assert "cat .env" not in install and "echo \"$" not in install.split("check_env")[1].split("}")[0]


# --------------------------------------------------------------------------
# G-B3 DEPLOY.md
# --------------------------------------------------------------------------

def test_b3_deploy_doc_sections_and_links():
    doc = (ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    for needle in ("Proxmox", "QEMU guest agent", "Start at boot", "unattended-upgrades", "ufw", "SSH", "статический IP",
                   "deploy/install.sh", "Contents: Read and write", "Cloudflare Tunnel", "secondbrain-core.com",
                   "deploy/update.sh", "deploy/backup.sh", "deploy/restore.sh", "migrate-from-old-pc.sh",
                   "export_tasks_to_note", "Сайт не открывается"):
        assert needle in doc, needle
    for f in ("README.md", "CLAUDE.md"):
        assert "docs/DEPLOY.md" in (ROOT / f).read_text(encoding="utf-8"), f


# --------------------------------------------------------------------------
# G-B4 verification of the prod config
# --------------------------------------------------------------------------

def test_b4_compose_config_validates_with_test_env():
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("docker CLI not available")
    env = {**os.environ, "ENV_FILE": ".env.test.example"}
    # --env-file: interpolation uses the dummy file, the real .env is never read (D23).
    out = subprocess.run([docker, "compose", "--env-file", ".env.test.example", "-f", "docker-compose.yml",
                          "-p", "secondbrain-test", "config", "--quiet"],
                         cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert (ROOT / ".env.test.example").is_file()


# G-C1 (VERIFY-1 spec gap): unknown fields of a task line survive an edit made on the site
def test_c1_unknown_fields_survive_a_site_edit(vault_user, remote, tmp_path):
    from core import tasks_service
    from core.models import Task
    tasks_service.sync_tasks(vault_user, force=True)
    task = Task.objects.get(user=vault_user, vault_id="a1b2c3")       # "- [/] Дописать отчёт 🔼 #dev 🆔 a1b2c3 ⏳ 2026-11-12"
    tasks_service.update_task(vault_user, task.pk, title="Дописать отчёт v2", status="done")
    line = [l for l in vh.remote_file(remote, vh.TASKS_NOTE, tmp_path).splitlines() if "a1b2c3" in l][0]
    assert line.startswith("- [x] Дописать отчёт v2 🔼 #dev") and "⏳ 2026-11-12" in line and "✅ " in line
