"""Smoke + access tests for every HTML page, and page-level business logic."""
import os
import time
from unittest import mock

import pytest
from django.test.utils import override_settings

from core.models import Task, ChatMessage, UserSettings

pytestmark = pytest.mark.django_db

PRIVATE_PAGES = ["/", "/chat/", "/notes/", "/tasks/", "/settings/"]
PRIVATE_APIS = ["/api/sidebar-stats/", "/api/get-note/?name=x", "/api/send-message/",
                "/api/save-settings/", "/api/add-task/", "/api/update-task/"]


@pytest.mark.parametrize("url", PRIVATE_PAGES + PRIVATE_APIS)
def test_anonymous_is_redirected_to_login(client, url):
    r = client.get(url)
    assert r.status_code == 302
    assert r.url.startswith("/login/?next=")


@pytest.mark.parametrize("url", ["/login/", "/register/"])
def test_public_pages_ok(client, url):
    assert client.get(url).status_code == 200


@pytest.mark.parametrize("url,title", [
    ("/", "Second Brain - Home"),
    ("/chat/", "AI Chat"),
    ("/notes/", "Synced Knowledge Base Vault"),
    ("/tasks/", "Second Brain - Tasks"),
    ("/settings/", "Settings"),
])
def test_private_pages_render_for_user(auth_client, url, title):
    r = auth_client.get(url)
    assert r.status_code == 200
    html = r.content.decode()
    assert title in html
    # shell: sidebar + mobile menu button + viewport meta
    assert 'id="main-sidebar"' in html and 'id="mobile-menu-open"' in html
    assert 'name="viewport"' in html
    assert "Operator: <span" in html and "alice" in html


def test_templates_use_debug_false_without_errors(auth_client):
    with override_settings(DEBUG=False):
        for url in PRIVATE_PAGES:
            assert auth_client.get(url).status_code == 200, url


def test_superuser_link_only_for_superuser(user, superuser):
    from django.test import Client
    normal, admin = Client(), Client()
    normal.force_login(user)
    admin.force_login(superuser)
    assert b"Core Matrix" not in normal.get("/").content
    assert b"Core Matrix" in admin.get("/").content


def test_base_layout_html_is_well_formed(auth_client):
    """#app-wrapper must be closed before </body>; scripts belong inside <body>."""
    html = auth_client.get("/").content.decode()
    body_close = html.index("</body>")
    assert html.rfind("<script", 0, len(html)) < body_close, "script tags after </body>"
    # count of opened/closed divs must match
    assert html.count("<div") == html.count("</div>")


# --- home -------------------------------------------------------------------

def test_home_dashboard_context(auth_client, user, other_user, note_writer):
    Task.objects.create(user=user, title="T-todo", tags="work, coding")
    Task.objects.create(user=user, title="T-prog", status="in_progress", tags="work")
    Task.objects.create(user=user, title="T-done", status="done", tags="ignored")
    Task.objects.create(user=other_user, title="FOREIGN", tags="other")
    for i in range(5):
        p = note_writer(user, f"note{i}", "x")
        os.utime(p, (time.time() - 1000 + i, time.time() - 1000 + i))
    r = auth_client.get("/")
    ctx = r.context
    assert [t.title for t in ctx["todo_tasks"]] == ["T-todo"]
    assert [t.title for t in ctx["progress_tasks"]] == ["T-prog"]
    assert [t.title for t in ctx["done_tasks"]] == ["T-done"]
    assert ctx["top_focus"] == "work"
    assert ctx["total_notes_count"] == 5
    assert [n["name"] for n in ctx["recent_notes"]] == ["note4", "note3", "note2"]
    assert b"FOREIGN" not in r.content


def test_home_without_tasks_and_notes(auth_client):
    r = auth_client.get("/")
    assert r.context["top_focus"] == "General Systems"
    assert r.context["total_notes_count"] == 0
    assert b"No tasks in your database yet." in r.content
    assert b"No notes found in matrix vault." in r.content


def test_home_recent_tasks_limited_to_four(auth_client, user):
    for i in range(6):
        Task.objects.create(user=user, title=f"t{i}")
    assert len(auth_client.get("/").context["recent_tasks"]) == 4


def test_home_escapes_task_title(auth_client, user):
    Task.objects.create(user=user, title="<script>alert(1)</script>")
    assert b"<script>alert(1)</script>" not in auth_client.get("/").content


# --- chat page --------------------------------------------------------------

def test_chat_page_lists_notes_and_history(auth_client, user, note_writer):
    for name in ["b", "a", "sub/c"]:
        note_writer(user, name, "x")
    ChatMessage.objects.create(user=user, role="user", content="question 1")
    ChatMessage.objects.create(user=user, role="ai", content="answer\nline2")
    r = auth_client.get("/chat/")
    assert r.context["all_files"] == ["a", "b", "c"]
    html = r.content.decode()
    assert "question 1" in html and "answer<br>line2" in html
    assert html.index("question 1") < html.index("answer<br>line2")


def test_chat_history_limited_to_last_50(auth_client, user):
    for i in range(55):
        ChatMessage.objects.create(user=user, role="user", content=f"msg-{i:02d}-end")
    html = auth_client.get("/chat/").content.decode()
    assert "msg-04-end" not in html and "msg-05-end" in html and "msg-54-end" in html


def test_chat_greeting_shown_when_history_empty(auth_client):
    assert b"Hello! I'm your AI assistant" in auth_client.get("/chat/").content


def test_chat_greeting_hidden_when_history_exists(auth_client, user):
    ChatMessage.objects.create(user=user, role="user", content="hi")
    assert b"Hello! I'm your AI assistant" not in auth_client.get("/chat/").content


def test_chat_page_context_preselects_first_ten(auth_client, user, note_writer):
    for i in range(12):
        note_writer(user, f"n{i:02d}", "x")
    ctx = auth_client.get("/chat/").context
    assert ctx["context_files"] == [f"n{i:02d}" for i in range(10)]
    assert len(ctx["all_files"]) == 12


# --- notes page -------------------------------------------------------------

def test_notes_page_lists_md_only(auth_client, user, note_writer, isolated_vault):
    note_writer(user, "Alpha", "a")
    note_writer(user, "folder/Beta", "b")
    with open(os.path.join(isolated_vault, "obsidian_data", f"user_{user.id}", "img.png"), "w") as f:
        f.write("x")
    r = auth_client.get("/notes/")
    assert sorted(r.context["user_notes"]) == ["Alpha", "Beta"]


def test_notes_page_triggers_sync_only_when_not_cloned(auth_client, user, isolated_vault):
    s = user.settings
    s.github_repo_url = "https://github.com/u/vault.git"
    s.github_token = "tok"
    s.save()
    with mock.patch("core.git_sync.sync_obsidian_repo") as sync:
        auth_client.get("/notes/")
        sync.assert_called_once()
        args = sync.call_args[0]
        assert args[0] == "https://github.com/u/vault.git" and args[1] == "tok"
        assert args[2].endswith(f"user_{user.id}")
        os.makedirs(os.path.join(args[2], ".git"))
        auth_client.get("/notes/")
        sync.assert_called_once()


def test_notes_page_without_repo_does_not_sync(auth_client):
    with mock.patch("core.git_sync.sync_obsidian_repo") as sync:
        r = auth_client.get("/notes/")
    sync.assert_not_called()
    assert b"No synced .md files found" in r.content


# --- tasks page -------------------------------------------------------------

def test_tasks_page_groups(auth_client, user, other_user):
    Task.objects.create(user=user, title="Active-1", priority="urgent", due_date="2026-01-02", tags="x")
    Task.objects.create(user=user, title="Prog-1", status="in_progress")
    Task.objects.create(user=user, title="Done-1", status="done")
    Task.objects.create(user=other_user, title="FOREIGN")
    r = auth_client.get("/tasks/")
    assert {t.title for t in r.context["active_tasks"]} == {"Active-1", "Prog-1"}
    assert [t.title for t in r.context["completed_tasks"]] == ["Done-1"]
    html = r.content.decode()
    assert "Urgent" in html and "2026-01-02" in html and "#x" in html
    assert "FOREIGN" not in html


def test_tasks_active_ordered_by_due_date(auth_client, user):
    Task.objects.create(user=user, title="ZZ_LATE", due_date="2026-03-01")
    Task.objects.create(user=user, title="ZZ_EARLY", due_date="2026-01-01")
    Task.objects.create(user=user, title="ZZ_MID", due_date="2026-02-01")
    titles = [t.title for t in auth_client.get("/tasks/").context["active_tasks"]]
    assert titles == ["ZZ_EARLY", "ZZ_MID", "ZZ_LATE"]
    html = auth_client.get("/tasks/").content.decode()
    assert html.index("ZZ_EARLY") < html.index("ZZ_MID") < html.index("ZZ_LATE")


def test_home_analytics_numbers(auth_client, user, note_writer):
    Task.objects.create(user=user, title="a")
    Task.objects.create(user=user, title="b")
    Task.objects.create(user=user, title="c", status="in_progress")
    note_writer(user, "n1", "x")
    html = auth_client.get("/").content.decode()
    assert "2 pending tasks" in html and "1 core notes" in html


def test_tasks_completed_limited_to_ten(auth_client, user):
    for i in range(12):
        Task.objects.create(user=user, title=f"d{i}", status="done")
    assert len(auth_client.get("/tasks/").context["completed_tasks"]) == 10


# --- settings page ----------------------------------------------------------

def test_settings_page_reflects_saved_values(auth_client, user):
    s = user.settings
    s.theme, s.accent_color, s.ai_strategy, s.temperature = "light", "green", "cloud_only", 0.3
    s.github_repo_url = "https://github.com/u/v.git"
    s.save()
    html = auth_client.get("/settings/").content.decode()
    assert 'data-theme="light"' in html and 'data-accent="green"' in html
    assert 'value="light" selected' in html
    assert 'value="green" checked' in html
    assert 'value="cloud_only" selected' in html
    assert 'value="https://github.com/u/v.git"' in html
    assert 'value="0.3"' in html


@pytest.mark.characterization
def test_settings_page_echoes_github_token_into_html(auth_client, user):
    """Q7: current behaviour — the PAT is rendered into the page source."""
    s = user.settings
    s.github_token = "ghp_visible"
    s.save()
    assert b'value="ghp_visible"' in auth_client.get("/settings/").content


# --- robustness: user without settings row -----------------------------------

@pytest.mark.parametrize("url", PRIVATE_PAGES + ["/api/sidebar-stats/"])
def test_pages_work_for_user_without_settings_row(auth_client, user, url):
    """A user whose UserSettings row was deleted (e.g. via Core Matrix 'Drop') must not get a 500."""
    UserSettings.objects.filter(user=user).delete()
    user.refresh_from_db()
    r = auth_client.get(url)
    assert r.status_code == 200
