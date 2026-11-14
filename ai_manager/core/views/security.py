"""Settings → 2FA (TOTP) endpoints (Round 5, F7). Session + CSRF like the other site APIs."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from .. import twofa
from ..models import get_user_settings
from .notes_api import _error, _post

PENDING_KEY = "sb_totp_setup_secret"


@login_required(login_url='login')
def totp_status(request):
    s = get_user_settings(request.user)
    return JsonResponse({"enabled": s.totp_enabled, "backup_codes_left": len(s.totp_backup_codes or [])})


@login_required(login_url='login')
def totp_setup(request):
    """New secret (kept in the session until confirmed) + otpauth URL + QR as inline SVG."""
    s = get_user_settings(request.user)
    if s.totp_enabled:
        return _error(400, "2FA уже включена. Чтобы сменить ключ, сначала отключите её.")
    secret = twofa.new_secret()
    request.session[PENDING_KEY] = secret
    url = twofa.otpauth_url(request.user.username, secret)
    return JsonResponse({"secret": secret, "otpauth_url": url, "qr_svg": twofa.qr_svg(url)})


@login_required(login_url='login')
def totp_enable(request):
    data, error = _post(request)
    if error:
        return error
    secret = request.session.get(PENDING_KEY)
    if not secret:
        return _error(400, "Сначала получите QR-код (настройка 2FA).")
    step = twofa.check_totp(secret, data.get("code"))
    if step is None:
        return _error(400, "Неверный код из приложения.")
    codes, hashes = twofa.new_backup_codes()
    s = get_user_settings(request.user)
    s.totp_secret, s.totp_enabled, s.totp_backup_codes, s.totp_last_step = secret, True, hashes, step
    s.save(update_fields=["totp_secret", "totp_enabled", "totp_backup_codes", "totp_last_step"])
    request.session.pop(PENDING_KEY, None)
    return JsonResponse({"status": "ok", "backup_codes": codes})


@login_required(login_url='login')
def totp_disable(request):
    data, error = _post(request)
    if error:
        return error
    s = get_user_settings(request.user)
    if not s.totp_enabled:
        return _error(400, "2FA не включена.")
    if not twofa.verify(s, data.get("code")):
        return _error(400, "Неверный код.")
    s.totp_enabled, s.totp_secret, s.totp_backup_codes, s.totp_last_step = False, "", [], 0
    s.save(update_fields=["totp_secret", "totp_enabled", "totp_backup_codes", "totp_last_step"])
    return JsonResponse({"status": "ok"})


@login_required(login_url='login')
def totp_backup_codes(request):
    data, error = _post(request)
    if error:
        return error
    s = get_user_settings(request.user)
    if not s.totp_enabled or not twofa.verify(s, data.get("code"), allow_backup=False):
        return _error(400, "Неверный код из приложения.")
    codes, hashes = twofa.new_backup_codes()
    s.totp_backup_codes = hashes
    s.save(update_fields=["totp_backup_codes"])
    return JsonResponse({"status": "ok", "backup_codes": codes})
