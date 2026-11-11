"""Login / logout / register views."""
import pytest
from django.contrib.auth.models import User

pytestmark = pytest.mark.django_db


def test_login_page_renders(client):
    r = client.get("/login/")
    assert r.status_code == 200
    assert b'name="username"' in r.content and b"csrfmiddlewaretoken" in r.content


def test_login_valid_credentials_redirects_home(client, user, password):
    r = client.post("/login/", {"username": "alice", "password": password})
    assert r.status_code == 302 and r.url == "/"
    assert client.get("/").status_code == 200


def test_login_invalid_credentials_shows_error(client, user):
    r = client.post("/login/", {"username": "alice", "password": "wrong"})
    assert r.status_code == 200
    assert b"Authentication failed" in r.content
    assert "_auth_user_id" not in client.session


def test_login_respects_next_parameter(client, user, password):
    """After login the user should land on the page they asked for (?next=)."""
    r = client.post("/login/?next=/tasks/", {"username": "alice", "password": password})
    assert r.status_code == 302 and r.url == "/tasks/"


def test_login_ignores_external_next(client, user, password):
    r = client.post("/login/?next=https://evil.example/", {"username": "alice", "password": password})
    assert r.status_code == 302 and r.url == "/"


def test_logged_in_user_is_redirected_from_login_and_register(auth_client):
    assert auth_client.get("/login/").url == "/"
    assert auth_client.get("/register/").url == "/"


def test_logout_ends_session(auth_client):
    r = auth_client.get("/logout/")
    assert r.status_code == 302 and r.url == "/login/"
    assert auth_client.get("/").status_code == 302


def test_register_page_renders_all_fields(client):
    r = client.get("/register/")
    assert r.status_code == 200
    for name in (b'name="username"', b'name="password1"', b'name="password2"'):
        assert name in r.content


def test_register_creates_user_settings_and_logs_in(client):
    r = client.post("/register/", {"username": "newbie", "password1": "Qwerty-Long-9876", "password2": "Qwerty-Long-9876"})
    assert r.status_code == 302 and r.url == "/"
    u = User.objects.get(username="newbie")
    assert u.settings.display_name == "newbie"
    assert int(client.session["_auth_user_id"]) == u.id


@pytest.mark.parametrize("data", [
    {"username": "x", "password1": "Qwerty-Long-9876", "password2": "different-9876"},
    {"username": "x", "password1": "123", "password2": "123"},
    {"username": "", "password1": "Qwerty-Long-9876", "password2": "Qwerty-Long-9876"},
])
def test_register_invalid_data_shows_error(client, data):
    r = client.post("/register/", data)
    assert r.status_code == 200
    assert b"Registration failed" in r.content
    assert not User.objects.filter(username="x").exists()


def test_register_duplicate_username_rejected(client, user):
    r = client.post("/register/", {"username": "alice", "password1": "Qwerty-Long-9876", "password2": "Qwerty-Long-9876"})
    assert r.status_code == 200
    assert User.objects.filter(username="alice").count() == 1


@pytest.mark.parametrize("nxt", ["foo", "logout", "//evil.example/x", "https://evil.example/"])
def test_login_with_odd_next_values_is_safe(client, user, password, nxt):
    """B-23: next must be treated as a URL, never as a URL-pattern name (was 500 / instant logout)."""
    r = client.post(f"/login/?next={nxt}", {"username": "alice", "password": password})
    assert r.status_code == 302
    assert r.url == "/"
    assert client.get("/").status_code == 200  # still logged in
