"""JSON API endpoints (integration via Django test client)."""
from unittest import mock

import pytest
from django.contrib.auth.models import User
from django.test import Client

from core.models import Task, ChatMessage, UserSettings

pytestmark = pytest.mark.django_db


@pytest.fixture
def no_raise_client(user):
    """Client that returns 500 responses instead of re-raising view exceptions."""
    c = Client(raise_request_exception=False)
    c.force_login(user)
    return c


# --- sidebar stats ----------------------------------------------------------

def test_sidebar_stats_counts_only_own_tasks(auth_client, user, other_user):
    Task.objects.create(user=user, title="a", status="done")
    Task.objects.create(user=user, title="b")
    Task.objects.create(user=user, title="c")
    Task.objects.create(user=other_user, title="x", status="done")
    assert auth_client.get("/api/sidebar-stats/").json() == {"status": "ok", "percent": 33, "done": 1, "total": 3}


def test_sidebar_stats_no_tasks(auth_client):
    assert auth_client.get("/api/sidebar-stats/").json()["percent"] == 0


# --- add task ---------------------------------------------------------------

def test_add_task_valid(auth_client, user, post_json):
    r = post_json(auth_client, "/api/add-task/", {"title": "Buy milk", "priority": "high", "due_date": "2026-12-01", "tags": "home"})
    assert r.status_code == 200 and r.json()["status"] == "ok"
    t = Task.objects.get(id=r.json()["task_id"])
    assert (t.user, t.title, t.priority, str(t.due_date), t.tags, t.status) == (user, "Buy milk", "high", "2026-12-01", "home", "todo")


def test_add_task_empty_due_date_is_null(auth_client, post_json):
    r = post_json(auth_client, "/api/add-task/", {"title": "x", "due_date": ""})
    assert Task.objects.get(id=r.json()["task_id"]).due_date is None


def test_add_task_get_not_allowed(auth_client):
    assert auth_client.get("/api/add-task/").status_code == 400


@pytest.mark.parametrize("payload", [
    {},                                   # no title
    {"title": ""},                        # empty title
    {"title": "   "},                     # blank title
    {"title": "x", "due_date": "not-a-date"},
    {"title": "x", "priority": "galactic"},
    {"title": "x" * 300},
    {"title": "x", "priority": ["high"]},
    {"title": {"a": 1}},
    {"title": "x", "tags": ["a", "b"]},
])
def test_add_task_invalid_payload_returns_400(no_raise_client, payload, post_json):
    r = post_json(no_raise_client, "/api/add-task/", payload)
    assert r.status_code == 400, r.content
    assert r.json()["status"] == "error"
    assert Task.objects.count() == 0


def test_add_task_malformed_json_returns_400(no_raise_client, post_json):
    r = post_json(no_raise_client, "/api/add-task/", raw="{not json")
    assert r.status_code == 400


# --- update task ------------------------------------------------------------

def test_update_task_status_own(auth_client, user, post_json):
    t = Task.objects.create(user=user, title="a")
    r = post_json(auth_client, "/api/update-task/", {"task_id": str(t.id), "status": "done"})
    assert r.json() == {"status": "ok"}
    t.refresh_from_db()
    assert t.status == "done"


def test_update_task_of_other_user_is_404(auth_client, other_user, post_json):
    t = Task.objects.create(user=other_user, title="theirs")
    r = post_json(auth_client, "/api/update-task/", {"task_id": t.id, "status": "done"})
    assert r.status_code == 404
    t.refresh_from_db()
    assert t.status == "todo"


def test_update_task_get_returns_400_not_500(no_raise_client):
    assert no_raise_client.get("/api/update-task/").status_code == 400


@pytest.mark.parametrize("payload", [
    {"task_id": "abc", "status": "done"},
    {"status": "done"},
])
def test_update_task_bad_id_returns_4xx(no_raise_client, payload, post_json):
    r = post_json(no_raise_client, "/api/update-task/", payload)
    assert r.status_code in (400, 404)


def test_update_task_rejects_non_string_status(no_raise_client, user, post_json):
    t = Task.objects.create(user=user, title="a")
    assert post_json(no_raise_client, "/api/update-task/", {"task_id": t.id, "status": ["done"]}).status_code == 400


def test_update_task_rejects_unknown_status(no_raise_client, user, post_json):
    t = Task.objects.create(user=user, title="a")
    r = post_json(no_raise_client, "/api/update-task/", {"task_id": t.id, "status": "exploded"})
    assert r.status_code == 400
    t.refresh_from_db()
    assert t.status == "todo"


# --- save settings ----------------------------------------------------------

FULL_SETTINGS = {
    "username": "alice2", "display_name": "alice2", "email": "a2@example.com",
    "theme": "light", "accent_color": "purple", "ai_strategy": "cloud_only",
    "temperature": "0.4", "github_repo_url": " https://github.com/u/v.git ", "github_token": " tok ",
}


def test_save_settings_full(auth_client, user, post_json):
    with mock.patch("core.rag_engine.reset_chat_engine") as reset:
        r = post_json(auth_client, "/api/save-settings/", FULL_SETTINGS)
    assert r.json() == {"status": "ok"}
    reset.assert_called_once_with(user.id)
    user.refresh_from_db()
    s = UserSettings.objects.get(user=user)
    assert (user.username, user.email) == ("alice2", "a2@example.com")
    assert (s.display_name, s.theme, s.accent_color, s.ai_strategy) == ("alice2", "light", "purple", "cloud_only")
    assert s.temperature == pytest.approx(0.4)
    assert s.github_repo_url == "https://github.com/u/v.git" and s.github_token == "tok"


@pytest.mark.parametrize("raw,expected", [("5", 1.0), ("-3", 0.0), ("abc", 0.7), (None, 0.7)])
def test_save_settings_temperature_clamped(auth_client, user, post_json, raw, expected):
    post_json(auth_client, "/api/save-settings/", {"temperature": raw})
    assert UserSettings.objects.get(user=user).temperature == pytest.approx(expected)


def test_save_settings_invalid_strategy_ignored(auth_client, user, post_json):
    post_json(auth_client, "/api/save-settings/", {"ai_strategy": "evil"})
    assert UserSettings.objects.get(user=user).ai_strategy == "auto"


def test_save_settings_partial_keeps_other_values(auth_client, user, post_json):
    post_json(auth_client, "/api/save-settings/", {"theme": "light"})
    user.refresh_from_db()
    assert user.username == "alice" and user.email == "alice@example.com"
    assert user.settings.theme == "light"


@pytest.mark.characterization
def test_save_settings_display_name_renames_login_username(auth_client, user, post_json):
    """Q6: the settings 'Display Name' field is sent as `username` and renames the login."""
    post_json(auth_client, "/api/save-settings/", {"username": "Neo", "display_name": "Neo"})
    user.refresh_from_db()
    assert user.username == "Neo"


def test_save_settings_empty_username_rejected(no_raise_client, user, post_json):
    r = post_json(no_raise_client, "/api/save-settings/", {"username": "", "display_name": ""})
    assert r.status_code == 400
    user.refresh_from_db()
    assert user.username == "alice"


def test_save_settings_taken_username_rejected(no_raise_client, user, other_user, post_json):
    r = post_json(no_raise_client, "/api/save-settings/", {"username": "bob", "display_name": "bob"})
    assert r.status_code == 400
    user.refresh_from_db()
    assert user.username == "alice"


def test_save_settings_null_values_do_not_crash(no_raise_client, user, post_json):
    s = user.settings
    s.github_repo_url, s.github_token = "https://github.com/u/v.git", "tok"
    s.save()
    r = post_json(no_raise_client, "/api/save-settings/", {"github_repo_url": None, "github_token": None, "display_name": None})
    assert r.status_code == 200
    s = UserSettings.objects.get(user=user)
    assert (s.github_repo_url, s.github_token, s.display_name) == ("https://github.com/u/v.git", "tok", "alice")


def test_save_settings_name_longer_than_display_name_field_rejected(no_raise_client, user, post_json):
    """display_name is max 100 chars (Postgres would raise DataError); user row must stay unchanged."""
    r = post_json(no_raise_client, "/api/save-settings/", {"username": "n" * 120, "display_name": "n" * 120})
    assert r.status_code == 400
    user.refresh_from_db()
    assert user.username == "alice"


def test_save_settings_malformed_json_400(no_raise_client, post_json):
    assert post_json(no_raise_client, "/api/save-settings/", raw="]]").status_code == 400


def test_save_settings_get_400(auth_client):
    assert auth_client.get("/api/save-settings/").status_code == 400


# --- chat message -----------------------------------------------------------

def test_send_message_persists_both_turns(auth_client, user, post_json):
    with mock.patch("core.rag_engine.ask_second_brain", return_value="AI says hi") as ask:
        r = post_json(auth_client, "/api/send-message/", {"message": "hello", "selected_files": ["a", 3, "b"]})
    assert r.json() == {"status": "ok", "reply": "AI says hi"}
    ask.assert_called_once()
    assert ask.call_args[0][0] == "hello" and ask.call_args[0][1] == user
    assert ask.call_args[0][2] == ["a", "b"]
    assert list(ChatMessage.objects.values_list("role", "content")) == [("user", "hello"), ("ai", "AI says hi")]


def test_send_message_legacy_key_and_bad_type(auth_client, post_json):
    with mock.patch("core.rag_engine.ask_second_brain", return_value="ok") as ask:
        post_json(auth_client, "/api/send-message/", {"message": "m", "selectedFiles": ["x"]})
        assert ask.call_args[0][2] == ["x"]
        post_json(auth_client, "/api/send-message/", {"message": "m", "selected_files": "x"})
        assert ask.call_args[0][2] == []


def test_send_message_empty_is_400(auth_client, post_json):
    with mock.patch("core.rag_engine.ask_second_brain") as ask:
        r = post_json(auth_client, "/api/send-message/", {"message": ""})
    assert r.status_code == 400
    ask.assert_not_called()
    assert ChatMessage.objects.count() == 0


def test_send_message_malformed_json_400(no_raise_client, post_json):
    assert post_json(no_raise_client, "/api/send-message/", raw="nope").status_code == 400


# --- get note ---------------------------------------------------------------

def test_get_note_renders_markdown_wikilinks_backlinks(auth_client, user, note_writer):
    note_writer(user, "Main", "# Title\n\nSee [[Other]] and [[Other|alias]].\n\n| a | b |\n|---|---|\n| 1 | 2 |\n")
    note_writer(user, "sub/Other", "plain")
    note_writer(user, "Ref", "intro text that links to [[Main]] here")
    d = auth_client.get("/api/get-note/", {"name": "Main"}).json()
    assert d["status"] == "ok"
    assert "<h1>Title</h1>" in d["html_content"]
    assert 'data-note="Other">Other</a>' in d["html_content"]
    assert 'data-note="Other">alias</a>' in d["html_content"]
    assert "<table>" in d["html_content"]
    assert d["backlinks"] == [{"title": "Ref", "snippet": "...intro text that links to [[Main]] here..."}]


def test_get_note_in_subfolder(auth_client, user, note_writer):
    note_writer(user, "deep/er/Leaf", "leaf body")
    assert "leaf body" in auth_client.get("/api/get-note/", {"name": "Leaf"}).json()["html_content"]


def test_get_note_missing_name_400(auth_client):
    assert auth_client.get("/api/get-note/").status_code == 400


def test_get_note_not_found_404(auth_client):
    assert auth_client.get("/api/get-note/", {"name": "nope"}).status_code == 404


def test_get_note_cannot_read_other_users_vault(auth_client, other_user, note_writer):
    note_writer(other_user, "Secret", "top secret")
    assert auth_client.get("/api/get-note/", {"name": "Secret"}).status_code == 404


def test_get_note_path_traversal_blocked(auth_client, other_user, note_writer):
    note_writer(other_user, "Secret", "top secret")
    r = auth_client.get("/api/get-note/", {"name": f"../user_{other_user.id}/Secret"})
    assert r.status_code == 404


def test_get_note_wikilink_target_is_attribute_escaped(auth_client, user, note_writer):
    note_writer(user, "X", '[[a" onmouseover="alert(1)]]')
    html = auth_client.get("/api/get-note/", {"name": "X"}).json()["html_content"]
    assert 'onmouseover="alert(1)"' not in html


# --- CSRF -------------------------------------------------------------------

@pytest.mark.parametrize("url,payload", [
    ("/api/add-task/", {"title": "csrf"}),
    ("/api/save-settings/", {"theme": "light"}),
    ("/api/send-message/", {"message": "hi"}),
])
def test_state_changing_api_requires_csrf_token(user, url, payload):
    c = Client(enforce_csrf_checks=True)
    c.force_login(user)
    with mock.patch("core.rag_engine.ask_second_brain", return_value="x"):
        r = c.post(url, data=payload, content_type="application/json")
    assert r.status_code == 403


def test_state_changing_api_accepts_csrf_header(user):
    c = Client(enforce_csrf_checks=True)
    c.force_login(user)
    c.get("/tasks/")  # sets csrftoken cookie
    token = c.cookies["csrftoken"].value
    r = c.post("/api/add-task/", data={"title": "ok"}, content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert r.status_code == 200
    assert Task.objects.filter(title="ok").exists()
