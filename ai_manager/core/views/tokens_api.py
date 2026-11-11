"""Session endpoints for API tokens in Settings (Round 4 / G-API1). CSRF-protected.

The raw token is returned ONCE by create; only its SHA-256 hash is stored.
"""
import datetime as _dt

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone

from ..models import ApiToken, clean_rights_paths
from .utils import parse_json_body


def _err(status, msg):
    return JsonResponse({"status": "error", "msg": msg}, status=status)


@login_required(login_url='login')
def token_create(request):
    if request.method != "POST":
        return _err(405, "POST only.")
    data = parse_json_body(request)
    if data is None:
        return _err(400, "Malformed JSON body.")
    name = str(data.get("name") or "").strip()
    if not name or len(name) > 60:
        return _err(400, "Название токена: 1–60 символов.")
    scopes = data.get("scopes")
    if not isinstance(scopes, list) or not scopes or any(s not in ApiToken.SCOPES for s in scopes):
        return _err(400, "Права: read, write, delete, ai.")
    expires_at = None
    days = data.get("expires_days")
    if days not in (None, "", 0):
        try:
            days = int(days)
        except (TypeError, ValueError):
            return _err(400, "Срок действия — число дней.")
        if not 1 <= days <= 3650:
            return _err(400, "Срок действия: 1–3650 дней.")
        expires_at = timezone.now() + _dt.timedelta(days=days)
    try:
        obj, raw = ApiToken.create_for(request.user, name=name, scopes=scopes, expires_at=expires_at,
                                       write_paths=data.get("write_paths") or [],
                                       delete_paths=data.get("delete_paths") or [])
    except ValueError as error:
        return _err(400, str(error))
    return JsonResponse({"status": "ok", "id": obj.pk, "token": raw, "prefix": obj.prefix})


@login_required(login_url='login')
def token_revoke(request):
    if request.method != "POST":
        return _err(405, "POST only.")
    data = parse_json_body(request) or {}
    updated = ApiToken.objects.filter(pk=data.get("id"), user=request.user, revoked_at__isnull=True) \
        .update(revoked_at=timezone.now())
    if not updated:
        return _err(404, "Токен не найден.")
    return JsonResponse({"status": "ok"})
