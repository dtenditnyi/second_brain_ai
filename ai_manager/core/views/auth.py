"""Authentication page controllers built on Django's standard forms and sessions."""
from django.shortcuts import render, redirect
from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.utils.http import url_has_allowed_host_and_scheme
from django.http import HttpResponseRedirect
import time

TWOFA_SESSION_KEY = "sb_2fa_pending"
TWOFA_TTL = 300
TWOFA_MAX_TRIES = 5
TWOFA_USER_FAILS = 10           # wrong codes per account per 15 minutes

# Register a new account, establish its authenticated session, or redisplay errors.
# Parameters: request contains registration form data on POST.
# Returns: a redirect after successful registration or the registration template.
def register_view(request):
    if request.user.is_authenticated:
        return redirect('home')
        
    error_message = None
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('home')
        else:
            error_message = "Registration failed. Invalid username or password patterns."
    else:
        form = UserCreationForm()
        
    return render(request, 'registration/register.html', {'form': form, 'error': error_message})

# Authenticate submitted credentials and create a Django login session on success.
# Parameters: request contains credentials on POST or renders a blank login form on GET.
# Returns: a redirect to the dashboard or the login template with validation errors.
def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')
        
    error_message = None
    if request.method == 'POST':
        form = AuthenticationForm(data=request.POST)
        if form.is_valid():
            user = form.get_user()
            next_url = request.POST.get('next') or request.GET.get('next')
            # Round 5 (F7): with 2FA on, the password only opens the second step.
            if getattr(getattr(user, 'settings', None), 'totp_enabled', False):
                request.session.cycle_key()
                request.session[TWOFA_SESSION_KEY] = {'uid': user.pk, 'backend': user.backend, 'next': next_url or '',
                                                      'at': int(time.time()), 'tries': 0}
                return redirect('login_2fa')
            login(request, user)
            # Honour ?next= for same-site targets only (B-12).
            # Only absolute same-site paths; never pass it to redirect(), which would
            # try to reverse() bare words like "foo"/"logout" (B-23).
            if next_url and next_url.startswith('/') and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return HttpResponseRedirect(next_url)
            return redirect('home')
        else:
            error_message = "Authentication failed. Invalid username or security credentials."
    else:
        form = AuthenticationForm()
        
    return render(request, 'registration/login.html', {'form': form, 'error': error_message})

# Terminate the current Django session and send the browser to the login page.
# Parameters: request is the active authenticated or anonymous HTTP request.
# Returns: an HTTP redirect to the login route.
def logout_view(request):
    logout(request)
    response = redirect('login')
    # Round 5 (F4): drop the offline copies of notes (service worker caches) on sign-out;
    # the login page also clears them by script (sb-clear-cache) for browsers without the header.
    response['Clear-Site-Data'] = '"cache"'
    return response


def _safe_next(request, next_url):
    if next_url and next_url.startswith('/') and url_has_allowed_host_and_scheme(
            next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return HttpResponseRedirect(next_url)
    return redirect('home')


def login_2fa_view(request):
    """Second login step: a TOTP code or a backup code (5 tries, 5 minutes)."""
    from django.contrib.auth.models import User
    from .. import twofa
    pending = request.session.get(TWOFA_SESSION_KEY)
    if not pending or time.time() - pending.get('at', 0) > TWOFA_TTL:
        request.session.pop(TWOFA_SESSION_KEY, None)
        return redirect('login')
    error_message = None
    if request.method == 'POST':
        from django.core.cache import cache
        fail_key = f"sb-2fa-fail:{pending['uid']}"
        user = User.objects.filter(pk=pending['uid'], is_active=True).select_related('settings').first()
        blocked = cache.get(fail_key, 0) >= TWOFA_USER_FAILS
        if user is not None and not blocked and twofa.verify(user.settings, request.POST.get('code', '')):
            cache.delete(fail_key)
            request.session.pop(TWOFA_SESSION_KEY, None)
            login(request, user, backend=pending.get('backend') or 'django.contrib.auth.backends.ModelBackend')
            return _safe_next(request, pending.get('next'))
        cache.set(fail_key, cache.get(fail_key, 0) + 1, 900)     # per account, across sessions
        pending['tries'] = pending.get('tries', 0) + 1
        if pending['tries'] >= TWOFA_MAX_TRIES:
            request.session.pop(TWOFA_SESSION_KEY, None)
            return redirect('login')
        request.session[TWOFA_SESSION_KEY] = pending
        error_message = "Неверный код. Попробуйте ещё раз (или резервный код)."
    return render(request, 'registration/login_2fa.html', {'error': error_message}, status=400 if error_message else 200)