"""Session JSON endpoints for the note editor (Round 4 / G-D1…D4). CSRF-protected like the rest."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from .. import notes_service
from ..vault_writer import VaultError
from .utils import parse_json_body


def _error(status, message, **extra):
    return JsonResponse({"status": "error", "msg": message, **extra}, status=status)


def _handle(fn):
    try:
        return fn()
    except notes_service.NoteConflict as conflict:
        return JsonResponse({"status": "conflict", "msg": str(conflict), "current_content": conflict.current_content,
                             "current_sha": conflict.current_sha, "diff": conflict.diff}, status=409)
    except notes_service.NoteError as error:
        return _error(error.status, str(error))
    except ValueError as error:
        return _error(400, str(error))
    except VaultError as error:
        return _error(503 if error.kind == "offline" else 409, str(error))


def _post(request):
    if request.method != "POST":
        return None, _error(405, "POST only.")
    data = parse_json_body(request)
    if data is None:
        return None, _error(400, "Malformed JSON body.")
    return data, None


@login_required(login_url='login')
def notes_names(request):
    return _handle(lambda: JsonResponse({"notes": notes_service.note_names(request.user)}))


@login_required(login_url='login')
def notes_meta(request):
    return _handle(lambda: JsonResponse(notes_service.meta(request.user)))


@login_required(login_url='login')
def notes_raw(request):
    path = request.GET.get("path") or ""
    if not path:
        return _error(400, "Параметр path обязателен.")
    return _handle(lambda: JsonResponse(notes_service.read_note(request.user, path)))


@login_required(login_url='login')
def notes_save(request):
    data, error = _post(request)
    if error:
        return error
    return _handle(lambda: JsonResponse({"status": "ok", **notes_service.save_note(
        request.user, data.get("path", ""), data.get("content"), data.get("base_sha"))}))


@login_required(login_url='login')
def notes_create(request):
    data, error = _post(request)
    if error:
        return error
    return _handle(lambda: JsonResponse({"status": "ok", "path": notes_service.create_note(
        request.user, folder=data.get("folder", ""), title=data.get("title"), template=data.get("template") or None,
        tags=data.get("tags") or [], moc=data.get("moc") or None, content=str(data.get("content") or ""))}))


@login_required(login_url='login')
def notes_delete(request):
    data, error = _post(request)
    if error:
        return error
    return _handle(lambda: JsonResponse({"status": "ok", "path": notes_service.delete_note(
        request.user, data.get("path", ""), base_sha=data.get("base_sha") or None)}))


@login_required(login_url='login')
def notes_rename(request):
    data, error = _post(request)
    if error:
        return error
    return _handle(lambda: JsonResponse({"status": "ok", **notes_service.rename_note(
        request.user, data.get("path", ""), data.get("new_path", ""), preview=bool(data.get("preview")),
        base_sha=data.get("base_sha") or None)}))
