"""Acceptance tests reuse the e2e fixtures (live server users, logged-in page)."""
from tests.e2e.conftest import browser_errors, e2e_admin, e2e_user, logged_page  # noqa: F401
