"""Q1: DEBUG comes from the environment (off by default), static files are served
by WhiteNoise after collectstatic, and the 404/500 pages render without errors."""
import os
import pathlib
import subprocess
import sys
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import Client

pytestmark = pytest.mark.django_db
ROOT = pathlib.Path(__file__).resolve().parent.parent


def _debug_value(settings_module, debug_env):
    env = dict(os.environ, DJANGO_SETTINGS_MODULE=settings_module, DEBUG=debug_env)
    out = subprocess.run(
        [sys.executable, "-c", "from django.conf import settings; print(settings.DEBUG)"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


@pytest.mark.parametrize("env_value,expected", [("False", "False"), ("True", "True"), ("yes", "False")])
def test_production_debug_follows_env(env_value, expected):
    assert _debug_value("ai_manager.settings", env_value) == expected


def test_debug_default_is_off_and_local_settings_turn_it_on():
    src = (ROOT / "ai_manager" / "settings.py").read_text(encoding="utf-8")
    assert "DEBUG = os.getenv('DEBUG', 'False') == 'True'" in src
    assert _debug_value("ai_manager.settings_local", "False") == "True"


def test_whitenoise_serves_collected_static_with_debug_off(tmp_path, settings):
    settings.DEBUG = False
    settings.STATIC_ROOT = tmp_path / "staticfiles"
    call_command("collectstatic", interactive=False, verbosity=0)
    assert (tmp_path / "staticfiles" / "css" / "styles.css").exists()
    response = Client().get("/static/css/styles.css")  # new client → new WhiteNoise instance
    assert response.status_code == 200
    body = b"".join(response.streaming_content) if response.streaming else response.content
    assert len(body) > 1000
    assert response["Content-Type"].startswith("text/css")
    js = Client().get("/static/js/csrf.js")
    assert js.status_code == 200


def test_404_page_renders_with_debug_off(client, settings):
    settings.DEBUG = False
    r = client.get("/definitely-missing-page/")
    assert r.status_code == 404
    html = r.content.decode()
    assert "Page not found" in html and 'href="/"' in html


def test_500_page_renders_with_debug_off(user, settings):
    settings.DEBUG = False
    c = Client(raise_request_exception=False)
    c.force_login(user)
    with mock.patch("core.views.pages.render", side_effect=RuntimeError("boom")):
        r = c.get("/tasks/")
    assert r.status_code == 500
    html = r.content.decode()
    assert "Something went wrong" in html and "boom" not in html
