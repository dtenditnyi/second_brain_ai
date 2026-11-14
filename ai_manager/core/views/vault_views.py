"""Round 5 (part F) — web version of the vault: search, tags, links, graph, tasks checkbox,
attachments, weekly notes, quick capture and the new pages (tags / graph / weekly).

Every endpoint is login-only and works on the signed-in user's own clone (paths are always
resolved inside it via ``safe_path``); writes go through ``vault_writer.vault_apply``.
"""
import datetime as _dt
import mimetypes
import os
from pathlib import Path, PurePosixPath

from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import render

from .. import api_v1, notes_service, vault_index, weekly
from ..models import get_user_settings
from ..vault_writer import UnsafePath, VaultError, safe_path
from .notes_api import _error, _handle, _post
from .utils import get_user_config

ATTACHMENT_DIR = "99 - Cache"
INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/avif", "image/svg+xml",
                "application/pdf", "audio/mpeg", "audio/ogg", "audio/wav", "audio/mp4", "video/mp4", "video/webm",
                "audio/x-wav", "audio/webm", "video/ogg"}
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("image/avif", ".avif")
mimetypes.add_type("audio/mp4", ".m4a")


def _root(request):
    return vault_index.user_root(request.user)


def _wrap(fn):
    """notes_api._handle + ApiError / WeeklyError → the site's JSON error format."""
    def run():
        try:
            return fn()
        except api_v1.ApiError as error:
            return _error(error.status, error.message)
        except weekly.WeeklyError as error:
            return _error(error.status, str(error))
    return _handle(run)


# --------------------------------------------------------------------------- F1 navigation & search

@login_required(login_url='login')
def notes_search(request):
    g = request.GET
    return _wrap(lambda: JsonResponse({"results": vault_index.search(
        request.user, q=g.get("q", ""), folder=g.get("folder", ""), tag=g.get("tag", ""),
        modified_after=g.get("after") or g.get("from"), modified_before=g.get("before") or g.get("to"))}))


@login_required(login_url='login')
def notes_mentions(request):
    def run():
        data = vault_index.mentions(request.user, request.GET.get("path", ""))
        return JsonResponse(data) if data else _error(404, "Заметка не найдена.")
    return _wrap(run)


@login_required(login_url='login')
def notes_graph(request):
    path = request.GET.get("path") or None
    return _wrap(lambda: JsonResponse(vault_index.graph(request.user, path)))


@login_required(login_url='login')
def notes_tree(request):
    favs = get_user_settings(request.user).favorite_notes or []
    try:
        return JsonResponse({"tree": vault_index.folder_tree(request.user), "recent": vault_index.recent(request.user),
                             "favorites": favs})
    except (VaultError, OSError):              # no vault yet / offline: the page still works
        return JsonResponse({"tree": None, "recent": [], "favorites": favs})


@login_required(login_url='login')
def notes_favorite(request):
    data, error = _post(request)
    if error:
        return error
    path = str(data.get("path") or "")
    try:
        safe_path(_root(request), path)
    except UnsafePath as exc:
        return _error(400, str(exc))
    s = get_user_settings(request.user)
    favs = [p for p in (s.favorite_notes or []) if p != path]
    if data.get("favorite", True):
        favs.insert(0, path)
    s.favorite_notes = favs[:50]
    s.save(update_fields=["favorite_notes"])
    return JsonResponse({"status": "ok", "favorites": s.favorite_notes})


@login_required(login_url='login')
def notes_toggle_task(request):
    data, error = _post(request)
    if error:
        return error
    line_no = data.get("line_no")
    line_no = int(line_no) if isinstance(line_no, (int, str)) and str(line_no).isdigit() else None
    return _wrap(lambda: JsonResponse({"status": "ok", **notes_service.set_task_status(
        request.user, data.get("path", ""), data.get("line"), data.get("status", "done"), line_no)}))


@login_required(login_url='login')
def attachment(request):
    """Serve an attachment from the user's vault (read-only, never .md/.git/.obsidian, never outside)."""
    try:
        root = _root(request)
    except VaultError:
        return HttpResponse("Not found", status=404, content_type="text/plain")
    rel, name = request.GET.get("path"), request.GET.get("name")
    target = None
    try:
        if rel:
            target = safe_path(root, rel)
        elif name and "/" not in name and "\\" not in name and name not in (".", ".."):
            preferred = root / ATTACHMENT_DIR
            for base in (preferred, root):
                if not base.is_dir():
                    continue
                for current, dirs, files in os.walk(base):
                    dirs[:] = sorted(d for d in dirs if d not in notes_service.SKIP_DIRS)
                    if name in files:
                        target = safe_path(root, (Path(current) / name).relative_to(root).as_posix())
                        break
                if target:
                    break
        else:
            return HttpResponse("Bad path", status=400, content_type="text/plain")
    except UnsafePath:
        return HttpResponse("Bad path", status=400, content_type="text/plain")
    if target is None or not target.is_file() or target.suffix.lower() == ".md":
        return HttpResponse("Not found", status=404, content_type="text/plain")
    ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    inline = ctype in INLINE_TYPES
    response = FileResponse(open(target, "rb"), content_type=ctype if inline else "application/octet-stream",
                            as_attachment=not inline, filename=target.name)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
    response["Cache-Control"] = "private, max-age=3600"
    return response


# --------------------------------------------------------------------------- F3 weekly

def _today(data):
    try:
        return _dt.date.fromisoformat(str(data.get("today"))[:10]) if data.get("today") else None
    except ValueError:
        return None


@login_required(login_url='login')
def weekly_this_week(request):
    data, error = _post(request)
    if error:
        return error
    return _wrap(lambda: JsonResponse({"status": "ok", **weekly.this_week(request.user, _today(data))}))


@login_required(login_url='login')
def weekly_carry_over(request):
    data, error = _post(request)
    if error:
        return error
    return _wrap(lambda: JsonResponse({"status": "ok", **weekly.carry_over(
        request.user, data.get("to", ""), preview=bool(data.get("preview")))}))


@login_required(login_url='login')
def weekly_calendar(request):
    return _wrap(lambda: JsonResponse(weekly.calendar(request.user)))


# --------------------------------------------------------------------------- F5 quick capture

@login_required(login_url='login')
def capture(request):
    data, error = _post(request)
    if error:
        return error
    client_id = str(data.get("client_id") or "")[:64]
    key = f"sb-capture:{request.user.pk}:{client_id}" if client_id else None
    if key and cache.get(key):
        return JsonResponse({"status": "ok", "duplicate": True, **cache.get(key)})

    def run():
        rel, commit = api_v1.capture_text(request.user, data.get("text"), data.get("target") or "inbox")
        result = {"path": rel, "commit": commit}
        if key:
            cache.set(key, result, 86400)
        return JsonResponse({"status": "ok", **result})
    return _wrap(run)


# --------------------------------------------------------------------------- pages

def _page(request, template, active, **extra):
    return render(request, template, {"active_page": active, "config": get_user_config(request.user), **extra})


def _safe(fn, default):
    try:
        return fn()
    except (VaultError, notes_service.NoteError, OSError):
        return default


@login_required(login_url='login')
def tags_page(request):
    tags = _safe(lambda: vault_index.tag_counts(request.user), [])
    return _page(request, "vault/tags.html", "notes", tags=tags)


@login_required(login_url='login')
def graph_page(request):
    return _page(request, "vault/graph.html", "notes", focus=request.GET.get("path", ""))


@login_required(login_url='login')
def weekly_page(request):
    data = _safe(lambda: weekly.calendar(request.user), {"weeks": [], "today": "", "this_week_start": ""})
    current = next((w for w in data["weeks"] if w["current"]), None)
    return _page(request, "vault/weekly.html", "weekly", weeks=list(reversed(data["weeks"])), current=current,
                 calendar=data)
