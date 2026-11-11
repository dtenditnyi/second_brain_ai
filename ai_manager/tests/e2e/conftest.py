"""Playwright E2E fixtures: Django live_server (in-process, so the HF/Git/LLM
mocks from tests/conftest.py also apply) + MS Edge via channel."""
import pytest

from tests.conftest import PASSWORD


@pytest.fixture
def e2e_user(transactional_db, django_user_model):
    return django_user_model.objects.create_user(username="e2e", password=PASSWORD)


@pytest.fixture
def e2e_admin(transactional_db, django_user_model):
    return django_user_model.objects.create_superuser(username="e2eroot", password=PASSWORD, email="r@x.io")


@pytest.fixture
def browser_errors(page):
    """Collect console errors, page exceptions and >=400 responses (favicon ignored)."""
    errors = []
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" and "favicon" not in m.text and "404 (Not Found)" not in m.text else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("response", lambda r: errors.append(f"HTTP {r.status} {r.url}") if r.status >= 400 and "favicon" not in r.url else None)
    return errors


def login(page, live_server, username, password=PASSWORD):
    page.goto(f"{live_server.url}/login/")
    page.fill("#id_username", username)
    page.fill("#id_password", password)
    page.click("button[type=submit]")
    page.wait_for_url(f"{live_server.url}/")


@pytest.fixture
def logged_page(page, live_server, e2e_user):
    login(page, live_server, "e2e")
    return page
