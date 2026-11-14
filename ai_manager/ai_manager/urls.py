"""Root URL composition for framework administration and the core application."""
from urllib.parse import urlencode

from django.contrib import admin
from django.http import HttpResponseRedirect
from django.urls import path, include, reverse
from django.utils.http import url_has_allowed_host_and_scheme


def admin_login_redirect(request):
    """Django admin's own login form knows nothing about 2FA (review R5, HIGH): every admin
    sign-in goes through the site's login (password → TOTP step), then back to the admin."""
    next_url = request.GET.get("next") or request.POST.get("next") or "/admin/"
    if not next_url.startswith("/") or not url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        next_url = "/admin/"
    return HttpResponseRedirect(f"{reverse('login')}?{urlencode({'next': next_url})}")


urlpatterns = [
    # Must stay before admin.site.urls: replaces /admin/login/ (no 2FA there).
    path('admin/login/', admin_login_redirect),
    # Django's built-in administrative site is mounted separately from Core Matrix.
    path('admin/', admin.site.urls),
    # Delegate application pages and APIs to the core URL namespace.
    path('', include('core.urls')),
]
