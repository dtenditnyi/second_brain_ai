"""Superuser 'Core Matrix' dashboard and its row APIs."""
import pytest
from django.contrib.auth.models import User
from django.test import Client

from core.models import Task, ChatMessage, UserSettings

pytestmark = pytest.mark.django_db


def test_dashboard_requires_superuser(client, auth_client):
    assert client.get("/system-matrix/").url.startswith("/login/")
    assert auth_client.get("/system-matrix/").url.startswith("/login/")


def test_dashboard_lists_all_tables(admin_client_, user):
    Task.objects.create(user=user, title="T1")
    ChatMessage.objects.create(user=user, role="user", content="M1")
    r = admin_client_.get("/system-matrix/")
    assert r.status_code == 200
    html = r.content.decode()
    for marker in ['data-model="users"', 'data-model="settings"', 'data-model="tasks"', 'data-model="messages"', "T1", "M1", "alice"]:
        assert marker in html


@pytest.mark.parametrize("url", ["/api/admin/update-row/", "/api/admin/delete-row/"])
def test_admin_api_forbidden_for_normal_user(auth_client, user, url, post_json):
    r = post_json(auth_client, url, {"table": "users", "id": user.id, "fields": {"is_superuser": "true"}})
    assert r.status_code in (302, 403)
    if r.status_code == 302:
        # must point at an existing login page (not Django's default /accounts/login/)
        assert r.url.startswith("/login/"), r.url
    user.refresh_from_db()
    assert not user.is_superuser and User.objects.filter(id=user.id).exists()


def test_admin_update_user(admin_client_, user, post_json):
    r = post_json(admin_client_, "/api/admin/update-row/", {"table": "users", "id": user.id, "fields": {"username": "al", "email": "e@x.io", "is_superuser": "true"}})
    assert r.json() == {"status": "ok"}
    user.refresh_from_db()
    assert (user.username, user.email, user.is_superuser) == ("al", "e@x.io", True)


def test_admin_update_settings(admin_client_, user, post_json):
    s = user.settings
    r = post_json(admin_client_, "/api/admin/update-row/", {"table": "settings", "id": s.id, "fields": {"display_name": "D", "theme": "light", "accent_color": "green", "ai_strategy": "local_only", "temperature": "0.2", "github_repo_url": "https://g/x"}})
    assert r.json()["status"] == "ok"
    s.refresh_from_db()
    assert (s.display_name, s.theme, s.accent_color, s.ai_strategy, s.temperature, s.github_repo_url) == ("D", "light", "green", "local_only", 0.2, "https://g/x")


def test_admin_update_task_and_message(admin_client_, user, post_json):
    t = Task.objects.create(user=user, title="a", due_date="2026-01-01")
    m = ChatMessage.objects.create(user=user, role="user", content="c")
    post_json(admin_client_, "/api/admin/update-row/", {"table": "tasks", "id": t.id, "fields": {"title": "b", "status": "done", "priority": "low", "tags": "q", "due_date": ""}})
    post_json(admin_client_, "/api/admin/update-row/", {"table": "messages", "id": m.id, "fields": {"role": "ai", "content": "d"}})
    t.refresh_from_db(); m.refresh_from_db()
    assert (t.title, t.status, t.priority, t.tags, t.due_date) == ("b", "done", "low", "q", None)
    assert (m.role, m.content) == ("ai", "d")


def test_admin_update_unknown_table_400(admin_client_, post_json):
    assert post_json(admin_client_, "/api/admin/update-row/", {"table": "x", "id": 1}).status_code == 400


def test_admin_update_missing_row_is_error(admin_client_, post_json):
    r = post_json(admin_client_, "/api/admin/update-row/", {"table": "tasks", "id": 9999, "fields": {}})
    assert r.status_code == 404 and r.json()["status"] == "error"


@pytest.mark.parametrize("table", ["users", "tasks", "messages"])
def test_admin_delete_row(admin_client_, user, table, post_json):
    obj = {"users": lambda: user,
           "tasks": lambda: Task.objects.create(user=user, title="a"),
           "messages": lambda: ChatMessage.objects.create(user=user, role="user", content="c")}[table]()
    r = post_json(admin_client_, "/api/admin/delete-row/", {"table": table, "id": obj.id})
    assert r.json() == {"status": "ok"}
    assert not type(obj).objects.filter(id=obj.id).exists()


def test_admin_delete_invalid_table(admin_client_, post_json):
    assert post_json(admin_client_, "/api/admin/delete-row/", {"table": "auth", "id": 1}).status_code == 400


def test_admin_get_methods_400(admin_client_):
    assert admin_client_.get("/api/admin/update-row/").status_code == 400
    assert admin_client_.get("/api/admin/delete-row/").status_code == 400


def test_admin_delete_requires_csrf(superuser, user):
    c = Client(enforce_csrf_checks=True)
    c.force_login(superuser)
    r = c.post("/api/admin/delete-row/", data={"table": "users", "id": user.id}, content_type="application/json")
    assert r.status_code == 403
    assert User.objects.filter(id=user.id).exists()


def test_django_admin_accessible_for_superuser(admin_client_):
    assert admin_client_.get("/admin/").status_code == 200


def test_dashboard_has_no_stray_debug_text(admin_client_, user):
    assert b"Anti-corruption layer code entry point" not in admin_client_.get("/system-matrix/").content


def test_admin_update_settings_empty_temperature_is_not_500(superuser, user, post_json):
    c = Client(raise_request_exception=False)
    c.force_login(superuser)
    r = post_json(c, "/api/admin/update-row/", {"table": "settings", "id": user.settings.id, "fields": {"temperature": ""}})
    assert r.status_code in (200, 400)
    user.settings.refresh_from_db()
    assert user.settings.temperature == 0.7


def test_admin_delete_settings_row_then_user_pages_still_work(admin_client_, user, post_json):
    sid = user.settings.id
    assert post_json(admin_client_, "/api/admin/delete-row/", {"table": "settings", "id": sid}).json()["status"] == "ok"
    c = Client()
    c.force_login(User.objects.get(id=user.id))
    assert c.get("/").status_code == 200


# --- Q11: a superuser cannot lock themself out -------------------------------

def test_superuser_cannot_remove_own_superuser_flag(admin_client_, superuser, post_json):
    r = post_json(admin_client_, "/api/admin/update-row/",
                  {"table": "users", "id": superuser.id, "fields": {"username": "root", "is_superuser": "false"}})
    assert r.status_code == 400
    superuser.refresh_from_db()
    assert superuser.is_superuser


def test_superuser_can_still_edit_own_row(admin_client_, superuser, post_json):
    r = post_json(admin_client_, "/api/admin/update-row/",
                  {"table": "users", "id": superuser.id,
                   "fields": {"username": "root", "email": "new@x.io", "is_superuser": "true"}})
    assert r.status_code == 200
    superuser.refresh_from_db()
    assert superuser.is_superuser and superuser.email == "new@x.io"


def test_missing_superuser_key_does_not_demote(admin_client_, superuser, user, post_json):
    user.is_superuser = True
    user.save()
    post_json(admin_client_, "/api/admin/update-row/", {"table": "users", "id": user.id, "fields": {"email": "e@x.io"}})
    user.refresh_from_db()
    assert user.is_superuser


def test_superuser_can_demote_someone_else(admin_client_, user, post_json):
    user.is_superuser = True
    user.save()
    post_json(admin_client_, "/api/admin/update-row/",
              {"table": "users", "id": user.id, "fields": {"is_superuser": "false"}})
    user.refresh_from_db()
    assert not user.is_superuser


@pytest.mark.parametrize("row_id", ["self_int", "self_str"])
def test_superuser_cannot_delete_own_account(admin_client_, superuser, post_json, row_id):
    rid = superuser.id if row_id == "self_int" else str(superuser.id)
    r = post_json(admin_client_, "/api/admin/delete-row/", {"table": "users", "id": rid})
    assert r.status_code == 400
    assert User.objects.filter(id=superuser.id).exists()


def test_own_row_controls_are_disabled_in_ui(admin_client_, superuser, user):
    html = admin_client_.get("/system-matrix/").content.decode()
    import re
    attr = re.compile(r'\sdisabled[\s>]')  # the attribute, not Tailwind's "disabled:" variant
    own = html.split(f'data-id="{superuser.id}" data-self="true"')[1].split("</tr>")[0]
    assert 'name="is_superuser"' in own
    assert len(attr.findall(own)) == 2  # superuser select + delete button
    other = html.split(f'<tr data-id="{user.id}"')[1].split("</tr>")[0]
    assert not attr.findall(other)


def test_back_to_dashboard_links_home(admin_client_):
    """Q4: "Back to Dashboard" leads to the home page."""
    html = admin_client_.get("/system-matrix/").content.decode()
    link = html.split("Back to Dashboard")[0].rsplit("<a ", 1)[1]
    assert 'href="/"' in link
