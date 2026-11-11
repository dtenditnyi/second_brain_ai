"""REST API v1 for the Telegram bot Link2Note and other clients (Round 4 / G-API1…API7).

Contract: ``docs/link2note/API_CONTRACT.md`` (wins over GOALS where they differ; the GOALS
endpoints are kept as aliases). Personal tokens (``Authorization: Bearer sb_…``, only the
SHA-256 hash is stored), scopes read / write / delete / ai, ``write_paths`` /
``delete_paths`` compared by whole path segments (empty = whole vault), per-token rate
limit, call log without bodies, ``Idempotency-Key`` on every mutating request (final
answers kept ≥ 7 days, compared by meaning), errors as
``{"error": {"code", "message", "retryable"}}`` + ``Retry-After``.
Every write goes through ``vault_writer.vault_apply`` (lock → pull → write → commit → push).
Session cookies are ignored: the API is token-only and CSRF-exempt.
"""
from __future__ import annotations

import datetime as _dt
import functools
import hashlib
import json
import logging
import math
import re
import time
import unicodedata
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.db import IntegrityError
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import frontmatter as fm
from . import notes_service, tasks_md, url_normalize
from .vault_writer import UnsafePath, VaultError, vault_apply, vault_read

logger = logging.getLogger("core.api")

API_VERSION = "1.4.0"
IDEMPOTENCY_KEEP_DAYS = 8                 # contract: ≥ 7 days
IN_PROGRESS_STALE = _dt.timedelta(minutes=10)
MUTATING = ("POST", "PUT", "PATCH", "DELETE")
_BAD_NAME = re.compile(r'[\\/:*?"<>|#^\[\]\x00-\x1f]')
PRIORITY_IN = {"urgent": "urgent", "high": "high", "normal": "medium", "medium": "medium", "low": "low"}
PRIORITY_OUT = {"urgent": "high", "high": "high", "medium": "normal", "low": "low"}
OPEN_STATES = ("todo", "in_progress", "forwarded")


class ApiError(Exception):
    def __init__(self, status, code, message, retryable=False, retry_after=None, **extra):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message
        self.retryable, self.retry_after, self.extra = retryable, retry_after, extra


def error_response(err):
    body = {"error": {"code": err.code, "message": err.message, "retryable": err.retryable}, **err.extra}
    resp = JsonResponse(body, status=err.status, json_dumps_params={"ensure_ascii": False})
    if err.retry_after:
        resp["Retry-After"] = str(int(err.retry_after))
    return resp


def ok(data, status=200):
    return JsonResponse(data, status=status, json_dumps_params={"ensure_ascii": False})


def no_content():
    return HttpResponse(status=204)


# --------------------------------------------------------------------------- auth, limits, log

def _bearer(request):
    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header[:7].lower() == "bearer ":
        return header[7:].strip()
    return ""


def authenticate(request):
    from .models import ApiToken
    token = ApiToken.authenticate(_bearer(request))
    if token is None:
        raise ApiError(401, "unauthorized", "Неверный, отозванный или просроченный токен.")
    return token


def _rate_limit(token):
    from .models import ApiCallLog
    limit = int(getattr(settings, "API_RATE_LIMIT_PER_MINUTE", 60) or 0)
    if limit <= 0:
        return
    since = timezone.now() - _dt.timedelta(seconds=60)
    recent = ApiCallLog.objects.filter(token=token, created_at__gte=since).exclude(status=429)
    if recent.count() >= limit:
        oldest = recent.order_by("created_at").values_list("created_at", flat=True).first()
        wait = 60 - (timezone.now() - oldest).total_seconds() if oldest else 60
        raise ApiError(429, "rate_limited", f"Слишком много запросов: не больше {limit} в минуту.",
                       retryable=True, retry_after=max(1, math.ceil(wait)))


def need(token, scope):
    if scope not in (token.scopes or []):
        raise ApiError(403, "forbidden", f"У токена нет права «{scope}».")


def _nfc(text):
    return unicodedata.normalize("NFC", str(text or ""))


def within(rel, roots):
    rel = _nfc(rel).strip("/")
    return any(rel == _nfc(r).strip("/") or rel.startswith(_nfc(r).strip("/") + "/") for r in roots)


def need_path(token, kind, rel):
    """kind 'write' | 'delete': scope + the path inside write_paths / delete_paths."""
    need(token, kind)
    roots = token.write_paths if kind == "write" else token.delete_paths
    if roots and not within(rel, roots):
        what = "записи" if kind == "write" else "удаления"
        raise ApiError(403, "forbidden", f"«{rel}» вне папок {what} этого токена.")


def _log_call(token, request, status, started):
    from .models import ApiCallLog
    try:
        ApiCallLog.objects.create(token=token, method=request.method[:10], path=request.path[:200], status=status,
                                  duration_ms=int((time.monotonic() - started) * 1000))
        token.touch()
    except Exception as error:  # the answer matters more than the journal
        logger.warning("API call log failed: %s.", type(error).__name__)


# --------------------------------------------------------------------------- idempotency

def _parse_body(request):
    if request.method not in MUTATING:
        return {}
    raw = request.body or b""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ApiError(400, "validation_error", "Тело запроса — не JSON.") from None
    if not isinstance(data, dict):
        raise ApiError(400, "validation_error", "Тело запроса должно быть JSON-объектом.")
    return data


def _fingerprint(request, data):
    canon = json.dumps([request.method, _nfc(request.path), sorted(request.GET.lists()), data],
                       sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _is_final(response):
    if response.status_code >= 500 or response.status_code == 429:
        return False
    if response.status_code == 409:
        try:
            return json.loads(response.content).get("error", {}).get("code") != "in_progress"
        except ValueError:
            return True
    return True


def _idempotent(request, token, data, run):
    from .models import IdempotencyRecord
    key = request.META.get("HTTP_IDEMPOTENCY_KEY", "").strip()
    if request.method not in MUTATING or not key:
        return run()
    if len(key) > 200:
        raise ApiError(400, "validation_error", "Idempotency-Key длиннее 200 символов.")
    fingerprint = _fingerprint(request, data)
    now = timezone.now()
    IdempotencyRecord.objects.filter(created_at__lt=now - _dt.timedelta(days=IDEMPOTENCY_KEEP_DAYS)).delete()
    try:
        record, created = IdempotencyRecord.objects.get_or_create(token=token, key=key,
                                                                  defaults={"fingerprint": fingerprint})
    except IntegrityError:
        record, created = IdempotencyRecord.objects.get(token=token, key=key), False
    if not created:
        if record.fingerprint != fingerprint:
            raise ApiError(409, "idempotency_mismatch", "Этот Idempotency-Key уже использован для другого запроса.")
        if not record.in_progress:
            resp = HttpResponse(record.body, status=record.status,
                                content_type="application/json" if record.body else None)
            resp["Idempotent-Replayed"] = "true"
            return resp
        if now - record.created_at < IN_PROGRESS_STALE:
            raise ApiError(409, "in_progress", "Запрос с этим Idempotency-Key ещё выполняется.",
                           retryable=True, retry_after=5)
        IdempotencyRecord.objects.filter(pk=record.pk).update(created_at=now)      # abandoned → take over
    try:
        response = run()
    except BaseException:
        IdempotencyRecord.objects.filter(pk=record.pk).delete()
        raise
    if _is_final(response):
        IdempotencyRecord.objects.filter(pk=record.pk).update(
            in_progress=False, status=response.status_code, body=response.content.decode("utf-8"))
    else:                                     # 5xx / 429 / in_progress: a retry runs again
        IdempotencyRecord.objects.filter(pk=record.pk).delete()
    return response


# --------------------------------------------------------------------------- endpoint decorator

def _map_exception(error):
    from .agent import AgentError
    from .tasks_service import TaskSyncError
    if isinstance(error, ApiError):
        return error
    if isinstance(error, notes_service.NoteConflict):
        return ApiError(409, "conflict", "Заметка изменилась: перечитайте её.", retryable=True,
                        current_sha=error.current_sha)
    if isinstance(error, notes_service.NoteError):
        return ApiError(404, "not_found", str(error)) if error.status == 404 else \
            ApiError(400, "validation_error", str(error))
    if isinstance(error, UnsafePath):
        return ApiError(400, "validation_error", str(error))
    if isinstance(error, VaultError):
        if error.kind == "locked":
            return ApiError(503, "vault_unavailable", "Хранилище занято, повторите позже.", retryable=True, retry_after=10)
        if error.kind == "permission":
            return ApiError(503, "vault_unavailable", "Сайт не может писать в хранилище (права токена GitHub).",
                            retryable=True, retry_after=300)
        return ApiError(503, "vault_unavailable", f"Хранилище недоступно: {error.message}", retryable=True,
                        retry_after=60)
    if isinstance(error, AgentError):
        code = {404: "not_found", 409: "conflict", 503: "vault_unavailable"}.get(error.status, "validation_error")
        return ApiError(error.status, code, str(error), retryable=error.status in (409, 503))
    if isinstance(error, TaskSyncError):
        return ApiError(503, "vault_unavailable", str(error), retryable=True, retry_after=60)
    if isinstance(error, (ValueError, fm.FrontmatterError)):
        return ApiError(422, "validation_error", str(error))
    return None


def endpoint(methods, public=False):
    def deco(fn):
        @csrf_exempt
        @functools.wraps(fn)
        def view(request, *args, **kwargs):
            started, token = time.monotonic(), None
            try:
                if request.method not in methods:
                    raise ApiError(405, "method_not_allowed", f"Метод {request.method} не поддерживается.")
                if not public:
                    token = authenticate(request)
                    _rate_limit(token)
                data = _parse_body(request)
                response = _idempotent(request, token, data,
                                       lambda: _call(fn, request, token, data, args, kwargs)) if token else \
                    _call(fn, request, token, data, args, kwargs)
            except ApiError as err:
                response = error_response(err)
            except Exception as error:  # pragma: no cover - last resort, no details leak
                logger.error("API %s %s failed: %s.", request.method, fn.__name__, type(error).__name__)
                response = error_response(ApiError(500, "internal_error", "Внутренняя ошибка сервера.", retryable=True))
            if token is not None:
                _log_call(token, request, response.status_code, started)
            return response
        return view
    return deco


def _call(fn, request, token, data, args, kwargs):
    try:
        return fn(request, token, data, *args, **kwargs)
    except Exception as error:
        mapped = _map_exception(error)
        if mapped is None:
            raise
        return error_response(mapped)


# --------------------------------------------------------------------------- vault helpers

def clean_rel(rel, md=True):
    """Contract path rules: no '..', '\\', ':', absolute paths, '.git' / '.obsidian' segments."""
    rel = _nfc(rel).strip()
    if not rel:
        raise ApiError(400, "validation_error", "Путь не указан.")
    parts = rel.split("/")
    if ("\\" in rel or ":" in rel or rel.startswith("/") or "\x00" in rel
            or any(p in ("", ".", "..") for p in parts)
            or any(p.casefold().rstrip(" .") in notes_service.SKIP_DIRS for p in parts)):
        raise ApiError(400, "validation_error", f"Недопустимый путь: {rel}")
    if md and not rel.lower().endswith(".md"):
        raise ApiError(400, "validation_error", "Нужен путь заметки .md.")
    return rel


def clean_folder(folder):
    folder = _nfc(folder).strip().strip("/")
    if not folder:
        return ""
    return clean_rel(folder, md=False)


def _root(user):
    """Fresh copy of the vault for reading (pull); the local clone when offline."""
    from .paths import get_user_paths
    try:
        return Path(vault_read(user, lambda r: r))
    except VaultError as error:
        local = Path(get_user_paths(user)["notes_dir"])
        if error.kind == "offline" and (local / ".git").exists():
            return local
        raise


def _read_file(root, rel):
    full = notes_service.md_path(root, rel)
    return full.read_bytes().decode("utf-8") if full.is_file() else None


def _short(commit):
    return (commit or "")[:7] or None


def _last_commit(user, rel):
    from . import vault_writer
    try:
        return vault_read(user, lambda root: vault_writer.Repo(root).git.log("-1", "--format=%h", "--", rel)) or None
    except Exception:
        return None


def _apply(user, operation, message):
    result, commit = vault_apply(user, operation, message, with_commit=True)
    return result, _short(commit)


def _title(content, name):
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return name


def _note_json(rel, content):
    return {"path": rel, "name": PurePosixPath(rel).stem, "content": content,
            "frontmatter": fm.parse(content) or {}, "sha": notes_service.sha(content)}


def check_content(content):
    """Contract checks for Markdown written by the API (POST/PUT/PATCH)."""
    if not isinstance(content, str):
        raise ApiError(422, "validation_error", "content должен быть строкой.")
    if len(content.encode("utf-8")) > 2_000_000:
        raise ApiError(422, "validation_error", "Заметка больше 2 МБ.")
    meta = fm.parse(content)
    if meta is None:
        raise ApiError(422, "validation_error", "В заметке нет frontmatter (--- … ---).")
    if meta.get("type") == "digest":
        if not meta.get("url"):
            raise ApiError(422, "validation_error", "У digest-заметки нет url.")
        if meta.get("status") not in ("unread", "read"):
            raise ApiError(422, "validation_error", "status должен быть unread или read.")
        tags = fm.tags_of(meta)
        bad = [t for t in tags if t not in tasks_md.ALLOWED_TAGS]
        if bad or len(tags) > 3:
            raise ApiError(422, "validation_error", f"Недопустимые теги: {tags} (не больше 3, только разрешённые).")
    return meta


def _check_sha(current, if_sha):
    if if_sha and if_sha != notes_service.sha(current):
        raise ApiError(409, "conflict", "if_sha не совпал: заметка изменилась.", retryable=True,
                       current_sha=notes_service.sha(current))


def _walk(root):
    for rel, full in notes_service._walk_md(root):
        try:
            yield rel, full.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue


# --------------------------------------------------------------------------- health / sync / schema

@endpoint(("GET",), public=True)
def health(request, token, data):
    from .models import ApiToken, VaultOutbox
    user_token = ApiToken.authenticate(_bearer(request)) if _bearer(request) else None
    synced, pending = None, 0           # without a token: no data about any user (VERIFY L6)
    if user_token is not None:
        s = user_token.user.settings
        if not s.github_repo_url:
            raise ApiError(503, "vault_unavailable", "Хранилище не подключено.", retryable=True, retry_after=300)
        synced, pending = s.tasks_last_sync, VaultOutbox.objects.filter(user=user_token.user).count()
    return ok({"status": "degraded" if pending else "ok",
               "vault_synced_at": synced.isoformat().replace("+00:00", "Z") if synced else None,
               "version": API_VERSION})


@endpoint(("GET",))
def sync_status(request, token, data):
    from .models import VaultOutbox
    need(token, "read")
    s = token.user.settings
    pending = VaultOutbox.objects.filter(user=token.user).count()
    return ok({"status": "degraded" if pending else "ok",
               "last_sync": s.tasks_last_sync.isoformat() if s.tasks_last_sync else None,
               "pending": pending, "error": s.tasks_sync_error or None})


@endpoint(("GET",), public=True)
def schema(request, token, data):
    return ok(openapi_schema())


# --------------------------------------------------------------------------- notes

@endpoint(("GET", "POST"))
def notes_collection(request, token, data):
    if request.method == "GET":
        need(token, "read")
        if request.GET.get("path"):
            return _read_note(token, request.GET["path"])
        return _list_notes(request, token)
    if "name" in data:
        return _create_from_markdown(token, data)
    return _create_from_fields(token, data)


def _read_note(token, raw_path):
    rel = clean_rel(raw_path)
    content = _read_file(_root(token.user), rel)
    if content is None:
        raise ApiError(404, "not_found", f"Заметки «{rel}» нет.")
    return ok(_note_json(rel, content))


def _list_notes(request, token):
    folder = clean_folder(request.GET.get("folder", ""))
    filters = {k[3:]: v for k, v in request.GET.items() if k.startswith("fm.")}
    try:
        limit = min(max(int(request.GET.get("limit", "100")), 1), 500)
    except ValueError:
        raise ApiError(400, "validation_error", "limit должен быть числом.") from None
    sort = request.GET.get("sort", "")
    if sort and not re.fullmatch(r"-?fm\.[\w.-]+", sort):
        raise ApiError(400, "validation_error", "sort: fm.<ключ> или -fm.<ключ>.")
    items = []
    for rel, content in _walk(_root(token.user)):
        if folder and not within(rel, [folder]):
            continue
        meta = fm.parse(content) or {}
        if any(not _fm_equals(meta.get(k), v) for k, v in filters.items()):
            continue
        name = PurePosixPath(rel).stem
        items.append({"path": rel, "name": name, "title": _title(content, name), "frontmatter": meta})
    if sort:
        field = sort.lstrip("-")[3:]
        items.sort(key=lambda it: (str(it["frontmatter"].get(field, "")), it["name"]), reverse=sort.startswith("-"))
    return ok({"items": items[:limit]})


def _fm_equals(value, expected):
    if isinstance(value, list):
        return expected in value or fm.render_value(value) == expected
    return value is not None and str(value) == expected


def _validate_name(name, limit=120):
    name = _nfc(name).strip() if isinstance(name, str) else ""
    if (not name or len(name) > limit or _BAD_NAME.search(name) or name.startswith(".")
            or name.rstrip(" .") != name):
        raise ApiError(422, "validation_error",
                       f"Недопустимое имя заметки (до {limit} символов, без \\ / : * ? \" < > | # ^ [ ]).")
    return name


def _create_from_markdown(token, data):
    """Contract POST /notes: Markdown written as is, name conflicts get « (2)», « (3)»…"""
    folder = clean_folder(data.get("folder", ""))
    name = _validate_name(data.get("name"))
    content = data.get("content")
    check_content(content)
    base = f"{folder}/{name}" if folder else name
    need_path(token, "write", f"{base}.md")

    def operation(root):
        rel, i = f"{base}.md", 2
        while notes_service.md_path(root, rel).exists():
            rel, i = f"{base} ({i}).md", i + 1
        full = notes_service.md_path(root, rel)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(content.encode("utf-8"))
        return [rel], rel

    rel, commit = _apply(token.user, operation, f"api: create {base}.md")
    notes_service._reindex(token.user, changed=[rel])
    return ok({"path": rel, "name": PurePosixPath(rel).stem, "sha": notes_service.sha(content),
               "commit": commit, "pushed": True}, status=201)


def _create_from_fields(token, data):
    """GOALS-style create: folder + title (+ template, tags, moc, content) → note with frontmatter."""
    folder = clean_folder(data.get("folder", ""))
    title = data.get("title")
    rel = f"{folder}/{title}.md" if folder else f"{title}.md"
    need_path(token, "write", rel)
    tags = data.get("tags") or []
    if not isinstance(tags, list):
        raise ApiError(422, "validation_error", "tags — список.")
    path = notes_service.create_note(token.user, folder=folder, title=title, template=data.get("template") or None,
                                     tags=tags, moc=data.get("moc") or None, content=str(data.get("content") or ""))
    return ok({"path": path, "name": PurePosixPath(path).stem, "pushed": True}, status=201)


@endpoint(("GET",))
def notes_search(request, token, data):
    need(token, "read")
    query = (request.GET.get("q") or "").strip()
    if not query:
        raise ApiError(400, "validation_error", "Параметр q обязателен.")
    q = query.casefold()
    titles, texts = [], []
    for rel, content in _walk(_root(token.user)):
        name = PurePosixPath(rel).stem
        aliases = notes_service._aliases(content)
        if any(q in n.casefold() for n in [name, *aliases]):
            titles.append({"path": rel, "name": name, "match": "title"})
            continue
        pos = content.casefold().find(q)
        if pos >= 0:
            texts.append({"path": rel, "name": name, "match": "text",
                          "snippet": content[max(0, pos - 60): pos + 100].replace("\n", " ")})
    return ok({"query": query, "results": (titles + texts)[:20]})


@endpoint(("GET",))
def notes_lookup(request, token, data):
    need(token, "read")
    key = url_normalize.normalize(request.GET.get("url", ""))
    if not key:
        raise ApiError(400, "validation_error", "Параметр url обязателен.")
    items = []
    for rel, content in _walk(_root(token.user)):
        meta = fm.parse(content) or {}
        url = meta.get("url")
        if isinstance(url, str) and url and url_normalize.normalize(url) == key:
            items.append({"path": rel, "name": PurePosixPath(rel).stem, "frontmatter": meta})
    return ok({"items": items})


@endpoint(("POST",))
def notes_append(request, token, data):
    rel = clean_rel(data.get("path", ""))
    need_path(token, "write", rel)
    text = data.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > 10000:
        raise ApiError(422, "validation_error", "text: от 1 до 10 000 символов.")
    notes_service.append_to_note(token.user, rel, text, message=f"api: append to {rel}")
    return ok({"path": rel, "pushed": True})


@endpoint(("GET", "PUT", "DELETE", "PATCH"))
def note_item(request, token, data, rest):
    rest = _nfc(rest).rstrip("/") if rest.endswith(".md/") else _nfc(rest)
    if rest.endswith("/frontmatter"):
        if request.method != "PATCH":
            raise ApiError(405, "method_not_allowed", "Для …/frontmatter — только PATCH.")
        return _patch_frontmatter(token, clean_rel(rest[: -len("/frontmatter")]), data)
    rel = clean_rel(rest)
    if request.method == "GET":
        need(token, "read")
        return _read_note(token, rel)
    if request.method == "PUT":
        return _put_note(token, rel, data)
    if request.method == "DELETE":
        return _delete_note(token, rel, request.GET.get("if_sha") or data.get("if_sha"))
    raise ApiError(405, "method_not_allowed", "PATCH — только для …/frontmatter.")


def _patch_frontmatter(token, rel, data):
    need_path(token, "write", rel)
    values = data.get("set")
    if not isinstance(values, dict) or not values:
        raise ApiError(422, "validation_error", "Нужен объект set с полями frontmatter.")
    if_sha = data.get("if_sha")

    def operation(root):
        current = _read_file(root, rel)
        if current is None:
            raise ApiError(404, "not_found", f"Заметки «{rel}» нет.")
        _check_sha(current, if_sha)
        new = fm.set_fields(current, values)
        check_content(new)
        if new == current:
            return [], (current, False)
        notes_service.md_path(root, rel).write_bytes(new.encode("utf-8"))
        return [rel], (new, True)

    (text, changed), commit = _apply(token.user, operation, f"api: frontmatter {rel}")
    if changed:
        notes_service._reindex(token.user, changed=[rel])
    return ok({"path": rel, "sha": notes_service.sha(text), "commit": commit or _last_commit(token.user, rel),
               "pushed": True})


def _put_note(token, rel, data):
    need_path(token, "write", rel)
    content, if_sha = data.get("content"), data.get("if_sha")
    if not isinstance(if_sha, str) or not if_sha:
        raise ApiError(422, "validation_error", "if_sha обязателен для PUT.")
    check_content(content)

    def operation(root):
        current = _read_file(root, rel)
        if current is None:
            raise ApiError(404, "not_found", f"Заметки «{rel}» нет.")
        _check_sha(current, if_sha)
        if current == content:
            return [], False
        notes_service.md_path(root, rel).write_bytes(content.encode("utf-8"))
        return [rel], True

    changed, commit = _apply(token.user, operation, f"api: edit {rel}")
    if changed:
        notes_service._reindex(token.user, changed=[rel])
    return ok({"path": rel, "sha": notes_service.sha(content), "commit": commit or _last_commit(token.user, rel),
               "pushed": True})


def _delete_note(token, rel, if_sha):
    need_path(token, "delete", rel)

    def operation(root):
        current = _read_file(root, rel)
        if current is None:
            raise ApiError(404, "not_found", f"Заметки «{rel}» нет.")
        _check_sha(current, if_sha)
        notes_service.md_path(root, rel).unlink()
        return [rel], rel

    _apply(token.user, operation, f"api: delete {rel}")
    notes_service._reindex(token.user, removed=[rel])
    return no_content()


@endpoint(("GET",))
def folders(request, token, data):
    need(token, "read")
    folder = clean_folder(request.GET.get("path", ""))
    root = _root(token.user)
    base = notes_service.md_path(root, f"{folder}/x.md" if folder else "x.md").parent
    if not base.is_dir():
        raise ApiError(404, "not_found", "Папка не найдена.")
    prefix = f"{folder}/" if folder else ""
    dirs = sorted(prefix + d.name for d in base.iterdir() if d.is_dir() and not d.name.startswith(".")
                  and d.name not in notes_service.SKIP_DIRS)
    notes = sorted(prefix + f.name for f in base.iterdir() if f.is_file() and f.suffix.lower() == ".md")
    return ok({"path": folder, "folders": dirs, "notes": notes})


# --------------------------------------------------------------------------- capture

def _entry(text, stamp):
    lines = text.strip().splitlines()
    first = f"- {stamp} {lines[0]}".rstrip() if stamp else f"- {lines[0]}"
    return "\n".join([first, *("  " + line if line.strip() else "" for line in lines[1:])]) + "\n"


def _insert_before_moc(text, entry):
    """Append, keeping a trailing «🔗 [[MOC]]» line last."""
    body = text if text.endswith("\n") or not text else text + "\n"
    lines = body.splitlines(keepends=True)
    tail = len(lines)
    while tail and not lines[tail - 1].strip():
        tail -= 1
    if tail and lines[tail - 1].lstrip().startswith("🔗"):
        head = "".join(lines[: tail - 1]).rstrip("\n")
        return (head + "\n" if head else "") + entry + "\n" + "".join(lines[tail - 1:])
    return body + entry


def _new_inbox(today):
    return (f"---\ntags: [planning]\ntype: inbox\nstatus: active\ndate: {today.isoformat()}\n"
            f"aliases: [Входящие, Inbox]\n---\n# 📥 Входящие\n\n🔗 [[{notes_service.DEFAULT_MOC}]]\n")


@endpoint(("POST",))
def capture(request, token, data):
    from . import weekly
    text, target = data.get("text"), data.get("target") or "inbox"
    if not isinstance(text, str) or not text.strip() or len(text) > 10000:
        raise ApiError(422, "validation_error", "text: от 1 до 10 000 символов.")
    if target not in ("inbox", "weekly", "week"):
        raise ApiError(422, "validation_error", "target: inbox или weekly.")
    now = timezone.localtime()
    if target == "inbox":
        rel = clean_rel(settings.CAPTURE_INBOX_NOTE)
        stamp = now.strftime("%Y-%m-%d %H:%M") + " —"
    else:
        _root(token.user)
        rel = weekly.current_week_note(token.user, today=now.date())
        if not rel:
            raise ApiError(404, "not_found", "Текущая недельная заметка не найдена (06 - Daily, type: weekly).")
        stamp = ""
    need_path(token, "write", rel)
    entry = _entry(text, stamp)

    def operation(root):
        current = _read_file(root, rel)
        if current is None:
            if target != "inbox":
                raise ApiError(404, "not_found", "Недельная заметка исчезла, повторите.")
            current = _new_inbox(now.date())
        full = notes_service.md_path(root, rel)
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(_insert_before_moc(current, entry).encode("utf-8"))
        return [rel], rel

    _, commit = _apply(token.user, operation, f"api: capture to {rel}")
    notes_service._reindex(token.user, changed=[rel])
    return ok({"path": rel, "name": PurePosixPath(rel).stem, "commit": commit, "pushed": True}, status=201)


# --------------------------------------------------------------------------- tasks

def _task_json(task, rel):
    tags = [t.strip() for t in (task.tags or "").replace(";", ",").split(",") if t.strip()]
    return {"id": task.vault_id or f"db-{task.pk}", "text": task.title,
            "status": "open" if task.status in OPEN_STATES else "done", "state": task.status,
            "due": task.due_date.isoformat() if task.due_date else None,
            "priority": PRIORITY_OUT.get(task.priority, "normal"), "priority_raw": task.priority,
            "tags": tags, "synced": task.synced, "path": rel}


def _find_task(user, task_id):
    from .models import Task
    task_id = str(task_id or "")
    qs = Task.objects.filter(user=user)
    task = qs.filter(pk=int(task_id[3:])).first() if task_id.startswith("db-") and task_id[3:].isdigit() \
        else qs.filter(vault_id=task_id).first()
    if task is None:
        raise ApiError(404, "not_found", f"Задачи {task_id} нет.")
    return task


def _date_or_none(value, field):
    if value in (None, ""):
        return None
    try:
        return _dt.date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ApiError(422, "validation_error", f"{field}: дата YYYY-MM-DD.") from None


def _tags_in(value):
    if value is None:
        return None
    if not isinstance(value, list):
        raise ApiError(422, "validation_error", "tags — список.")
    try:
        return tasks_md.validate_tags(value)
    except ValueError as error:
        raise ApiError(422, "validation_error", str(error)) from None


def _status_in(value):
    if value in (None, ""):
        return None
    mapped = {"open": "todo", "done": "done"}.get(value, value)
    if mapped not in tasks_md.MARK_BY_STATUS:
        raise ApiError(422, "validation_error", "status: open | done (или todo/in_progress/cancelled/forwarded).")
    return mapped


def _priority_in(value):
    if value in (None, ""):
        return None
    if value not in PRIORITY_IN:
        raise ApiError(422, "validation_error", "priority: high | normal | low.")
    return PRIORITY_IN[value]


@endpoint(("GET", "POST"))
def tasks_collection(request, token, data):
    from . import tasks_service
    from .models import Task
    rel = tasks_service.tasks_note_path(token.user)
    if request.method == "GET":
        need(token, "read")
        try:
            tasks_service.sync_tasks(token.user)
        except Exception as error:   # the cached list is still useful
            logger.warning("API tasks sync failed: %s.", type(error).__name__)
        qs = Task.objects.filter(user=token.user).order_by("due_date", "id")
        status = request.GET.get("status")
        if status == "open":
            qs = qs.filter(status__in=OPEN_STATES)
        elif status:
            qs = qs.filter(status=_status_in(status))
        if request.GET.get("due_before"):
            qs = qs.filter(due_date__isnull=False, due_date__lte=_date_or_none(request.GET["due_before"], "due_before"))
        items = [_task_json(t, rel) for t in qs]
        if request.GET.get("tag"):
            items = [t for t in items if request.GET["tag"] in t["tags"]]
        return ok({"items": items, "tasks": items})
    need_path(token, "write", rel)
    text = data.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ApiError(422, "validation_error", "text обязателен.")
    task = tasks_service.add_task(token.user, " ".join(text.split()), due=_date_or_none(data.get("due"), "due"),
                                  priority=_priority_in(data.get("priority")) or "medium",
                                  tags=_tags_in(data.get("tags")) or [], status=_status_in(data.get("status")))
    task.refresh_from_db()
    return ok({**_task_json(task, rel), "pushed": bool(task.synced)}, status=201)


@endpoint(("PATCH", "DELETE"))
def task_item(request, token, data, task_id):
    from . import tasks_service
    rel = tasks_service.tasks_note_path(token.user)
    need_path(token, "write", rel)
    task = _find_task(token.user, task_id)
    if request.method == "DELETE":
        tasks_service.delete_task(token.user, task.pk)
        return no_content()
    fields = {}
    if "text" in data:
        if not isinstance(data["text"], str) or not data["text"].strip():
            raise ApiError(422, "validation_error", "text не может быть пустым.")
        fields["title"] = " ".join(data["text"].split())
    if "status" in data:
        fields["status"] = _status_in(data["status"]) or "todo"
    if "due" in data:
        fields["due_date"] = _date_or_none(data["due"], "due")
    if "priority" in data:
        fields["priority"] = _priority_in(data["priority"]) or "medium"
    if "tags" in data:
        fields["tags"] = _tags_in(data["tags"]) or []
    if not fields:
        raise ApiError(422, "validation_error", "Нечего менять.")
    try:
        tasks_service.update_task(token.user, task.pk, **fields)
    except tasks_service.TaskSyncError as error:
        if str(error) == tasks_service.DELETED_ELSEWHERE:
            raise ApiError(404, "not_found", str(error)) from None
        raise
    return ok(_task_json(_find_task(token.user, task.vault_id or f"db-{task.pk}"), rel))


# --------------------------------------------------------------------------- ask / agent

@endpoint(("POST",))
def ask(request, token, data):
    from . import rag_engine
    from .paths import get_user_paths
    need(token, "ai")
    question, provider = data.get("question"), data.get("provider")
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        raise ApiError(422, "validation_error", "question: от 1 до 4000 символов.")
    if provider not in (None, "", "gemini", "claude", "ollama"):
        raise ApiError(422, "validation_error", "provider: gemini | claude | ollama | null.")
    sources = []
    answer = rag_engine.ask_second_brain(question.strip(), token.user, provider=provider or None, sources=sources)
    if not rag_engine.is_answer_text(answer):
        raise ApiError(503, "ai_unavailable", str(answer)[:500], retryable=True, retry_after=60)
    root = Path(get_user_paths(token.user)["notes_dir"]).resolve()
    out = []
    for path in sources:
        try:
            rel = Path(path).resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        out.append({"path": rel, "name": PurePosixPath(rel).stem})
    token.user.settings.refresh_from_db()
    return ok({"answer_markdown": answer, "answer": answer, "sources": out,
               "model": token.user.settings.last_model_used or None})


@endpoint(("POST",))
def agent_run(request, token, data):
    from . import agent
    need(token, "ai")
    text = data.get("request")
    if not isinstance(text, str) or not text.strip():
        raise ApiError(422, "validation_error", "request обязателен.")
    run = agent.run_agent(token.user, text, auto_apply=False)
    batch = agent.batch_json(run.batch)
    return ok({"text": run.text, "steps": run.steps, "provider": run.provider,
               "batch_id": batch["id"] if batch else None, "status": batch["status"] if batch else None,
               "changes": batch["changes"] if batch else []})


@endpoint(("POST",))
def agent_action(request, token, data, batch_id, action):
    from . import agent
    batch = agent._get_batch(token.user, batch_id)
    if action == "apply":
        indices = data.get("indices")
        if indices is not None and (not isinstance(indices, list) or not all(isinstance(i, int) for i in indices)):
            raise ApiError(422, "validation_error", "indices — список чисел.")
        for i, change in enumerate(batch.changes):
            if change.get("pending", True) and (indices is None or i in indices):
                need_path(token, "write", change["path"])
        return ok({"batch": agent.batch_json(agent.apply_batch(token.user, batch.pk, indices=indices))})
    need(token, "write")
    if action == "revert":       # a revert rewrites applied files and deletes created notes (VERIFY M1)
        for change in batch.changes:
            if change.get("applied"):
                need_path(token, "write", change["path"])
                if change["kind"] == "create":
                    need_path(token, "delete", change["path"])
    fn = agent.reject_batch if action == "reject" else agent.revert_batch
    return ok({"batch": agent.batch_json(fn(token.user, batch.pk))})


# --------------------------------------------------------------------------- OpenAPI

def openapi_schema():
    def op(summary, scope=None, body=None, ok_code="200", params=()):
        item = {"summary": summary, "responses": {ok_code: {"description": "OK"},
                                                  "4XX": {"$ref": "#/components/responses/Error"}}}
        if scope:
            item["security"] = [{"bearer": []}]
            item["description"] = f"Право токена: {scope}."
        if body:
            item["requestBody"] = {"content": {"application/json": {"schema": {"type": "object", "properties": body}}}}
        if params:
            item["parameters"] = [{"name": p, "in": "query", "schema": {"type": "string"}} for p in params]
        return item

    s = {"type": "string"}
    p = "/api/v1"
    paths = {
        f"{p}/health": {"get": op("Доступность и синхронизация (без токена)")},
        f"{p}/sync/": {"get": op("Статус синхронизации", "read")},
        f"{p}/notes/": {"get": op("Список заметок (folder, fm.*, sort, limit) или чтение ?path=", "read",
                                  params=("folder", "sort", "limit", "path")),
                        "post": op("Создать заметку: {folder, name, content} (готовый Markdown) или {folder, title, tags}",
                                   "write", {"folder": s, "name": s, "content": s, "title": s}, "201")},
        f"{p}/notes/lookup": {"get": op("Найти заметки по нормализованному url", "read", params=("url",))},
        f"{p}/notes/search/": {"get": op("Поиск по названию, алиасам и тексту", "read", params=("q",))},
        f"{p}/notes/append/": {"post": op("Дописать в заметку", "write", {"path": s, "text": s})},
        f"{p}/notes/{{path}}": {"get": op("Прочитать заметку", "read"),
                                "put": op("Заменить содержимое (if_sha обязателен)", "write", {"content": s, "if_sha": s}),
                                "delete": op("Удалить (?if_sha=)", "delete", ok_code="204")},
        f"{p}/notes/{{path}}/frontmatter": {"patch": op("Изменить поля frontmatter", "write", {"set": {"type": "object"}, "if_sha": s})},
        f"{p}/folders/": {"get": op("Подпапки и заметки папки", "read", params=("path",))},
        f"{p}/capture/": {"post": op("Быстрый захват: target inbox | weekly", "write", {"text": s, "target": s}, "201")},
        f"{p}/tasks/": {"get": op("Список задач (status, due_before, tag)", "read", params=("status", "due_before", "tag")),
                        "post": op("Создать задачу", "write", {"text": s, "due": s, "priority": s,
                                                               "tags": {"type": "array", "items": s}}, "201")},
        f"{p}/tasks/{{id}}": {"patch": op("Изменить задачу", "write", {"status": s, "due": s, "priority": s, "text": s}),
                              "delete": op("Удалить задачу", "write", ok_code="204")},
        f"{p}/ask/": {"post": op("Вопрос ИИ по заметкам", "ai", {"question": s, "provider": s})},
        f"{p}/agent/": {"post": op("Агент: запрос → пакет изменений (дифф)", "ai", {"request": s})},
        f"{p}/agent/{{id}}/apply/": {"post": op("Применить пакет (или indices)", "write", {"indices": {"type": "array"}})},
        f"{p}/agent/{{id}}/reject/": {"post": op("Отклонить пакет", "write")},
        f"{p}/agent/{{id}}/revert/": {"post": op("Откатить применённый пакет", "write")},
        f"{p}/schema/": {"get": op("Эта схема (без токена)")},
    }
    return {
        "openapi": "3.1.0",
        "info": {"title": "Second Brain API", "version": API_VERSION,
                 "description": "Токен: Authorization: Bearer sb_… Изменяющие запросы принимают Idempotency-Key. "
                                "Ошибки: {\"error\": {\"code\", \"message\", \"retryable\"}}. Документация: docs/API.md."},
        "components": {
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
            "responses": {"Error": {"description": "Ошибка", "content": {"application/json": {"schema": {
                "type": "object", "properties": {"error": {"type": "object", "properties": {
                    "code": s, "message": s, "retryable": {"type": "boolean"}}}}}}}}},
        },
        "paths": paths,
    }
