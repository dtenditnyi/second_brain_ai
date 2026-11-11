"""Tasks live in one Obsidian note; the ``Task`` table is only a cache (Round 3 / G-C3…C7).

* Reading: ``sync_tasks(user)`` pulls the vault (at most every TASKS_SYNC_INTERVAL
  seconds unless forced), sends queued offline operations first, then rebuilds
  the user's ``Task`` rows from the note.
* Writing: ``add_task`` / ``update_task`` / ``delete_task`` turn a UI action into
  a ``tasks_md`` operation by stable 🆔 and push it through ``vault_writer``. The
  cache row changes immediately; when GitHub is unreachable the operation is
  stored in ``VaultOutbox`` and the row is marked "не синхронизировано".
* Users without a connected repository keep the old database-only tasks.
"""
from __future__ import annotations

import datetime as _dt
import logging

from django.conf import settings as dj_settings
from django.db import transaction
from django.utils import timezone

from . import tasks_md
from .vault_writer import PERMISSION_HINT, VaultError, safe_path, vault_apply, vault_read

logger = logging.getLogger("core.tasks")

DELETED_ELSEWHERE = "Задача была удалена или изменена в Obsidian — список обновлён."


class TaskSyncError(Exception):
    pass


# --------------------------------------------------------------------------- helpers

def _settings(user):
    from .models import get_user_settings
    return get_user_settings(user)


def tasks_note_path(user) -> str:
    return (_settings(user).tasks_note_path or "").strip() or dj_settings.TASKS_NOTE_PATH


def vault_configured(user) -> bool:
    return bool(_settings(user).github_repo_url)


def _tags_list(value):
    if isinstance(value, (list, tuple)):
        return [str(t).strip().lstrip("#") for t in value if str(t).strip()]
    return [t.strip().lstrip("#") for t in str(value or "").replace(";", ",").replace(" ", ",").split(",") if t.strip()]


def _record_error(user, message):
    s = _settings(user)
    s.tasks_sync_error = message[:1000]
    s.save(update_fields=["tasks_sync_error"])


def _note_operation(user, ops):
    """vault_writer operation: ensure the note exists, give IDs, apply ``ops`` in order."""
    rel = tasks_note_path(user)

    def operation(root):
        path = safe_path(root, rel)
        original = path.read_bytes().decode("utf-8") if path.exists() else None
        text = original if original is not None else tasks_md.new_tasks_note()
        results = []
        for op in ops:
            try:
                text, info = tasks_md.apply_op(text, op)
                results.append(info)
            except tasks_md.TaskNotFound:
                results.append({"missing": True, "id": op.get("id")})
        # IDs for lines without one AFTER the ops: an op may address such a line
        # by its exact text, which giving it an ID first would change.
        text, _ = tasks_md.apply_op(text, {"op": "ensure_ids"})
        if text == original:
            return [], results
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return [rel], results

    return operation


def _commit_message(ops):
    if len(ops) == 1:
        op = ops[0]
        label = {"add": "add", "update": "update", "delete": "delete"}.get(op["op"], op["op"])
        detail = op.get("text") or op.get("id") or ""
        return f"tasks: {label} {detail}".strip()[:120]
    return f"tasks: sync {len(ops)} change(s) from Second Brain"


def _write(user, ops):
    """Send queued + new operations in order. Returns results for ``ops`` or None (queued offline)."""
    from .models import VaultOutbox
    pending = list(VaultOutbox.objects.filter(user=user).order_by("id"))
    all_ops = [row.op for row in pending] + list(ops)
    try:
        results = vault_apply(user, _note_operation(user, all_ops), _commit_message(all_ops))
    except VaultError as error:
        if error.kind == "offline":
            for op in ops:
                VaultOutbox.objects.create(user=user, op=op, last_error=error.message[:500])
            VaultOutbox.objects.filter(pk__in=[r.pk for r in pending]).update(attempts=1, last_error=error.message[:500])
            _record_error(user, error.message)
            logger.warning("Tasks write queued offline: %s op(s).", len(ops))
            return None
        if error.kind == "permission":
            _record_error(user, PERMISSION_HINT)
            raise TaskSyncError(PERMISSION_HINT) from error
        _record_error(user, error.message)
        raise TaskSyncError(error.message) from error
    VaultOutbox.objects.filter(pk__in=[r.pk for r in pending]).delete()
    if pending:
        from .models import Task
        Task.objects.filter(user=user, synced=False).update(synced=True)
    _record_error(user, "")
    return results[len(pending):]


# --------------------------------------------------------------------------- reading

def _cache_from_note(user, text):
    """Rebuild the user's Task rows from the note text (the source of truth)."""
    from .models import Task
    note = tasks_md.parse(text)
    keep = []
    with transaction.atomic():
        existing = list(Task.objects.filter(user=user))
        by_vid = {t.vault_id: t for t in existing if t.vault_id}
        by_line = {t.vault_line: t for t in existing if not t.vault_id and t.vault_line}
        seen_ids = set()
        for position, line in enumerate(note.tasks):
            # A repeated 🆔 (not fixed yet, e.g. offline) is identified by its line,
            # so it never collapses into the first task with that ID (B-34).
            line_id = line.id if line.id and line.id not in seen_ids else None
            if line_id:
                seen_ids.add(line_id)
            task = by_vid.get(line_id) if line_id else by_line.get(line.raw)
            if task is None or task.pk in keep:
                task = Task(user=user)
            task.title = (line.text or "(без названия)")[:255]
            task.status = line.status
            task.priority = line.priority or "medium"
            task.due_date = _dt.date.fromisoformat(line.due) if line.due else None
            task.tags = ", ".join(line.tags)[:100]
            task.vault_id = line_id or ""
            task.vault_line = line.raw[:2000]
            task.section = (line.section or "")[:120]
            task.position = position
            task.synced = True
            task.save()
            keep.append(task.pk)
        # Rows that never were in the note (old database-only tasks, see
        # export_tasks_to_note) are kept: connecting a vault must not lose them.
        Task.objects.filter(user=user).exclude(pk__in=keep).exclude(vault_id="", vault_line="").delete()


def _read_note(user):
    rel = tasks_note_path(user)

    def reader(root):
        path = safe_path(root, rel)
        return path.read_bytes().decode("utf-8") if path.exists() else None

    return vault_read(user, reader)


def _has_duplicate_ids(text):
    ids = [t.id for t in tasks_md.parse(text).tasks if t.id]
    return len(ids) != len(set(ids))


def _sync_now(user):
    """Flush the outbox, pull, rebuild the cache. Returns a status dict (never raises VaultError)."""
    from .models import VaultOutbox
    s = _settings(user)
    try:
        if VaultOutbox.objects.filter(user=user).exists():
            if _write(user, []) is None:
                return {"status": "offline", "error": s.tasks_sync_error}
        text = _read_note(user)
        if text and _has_duplicate_ids(text):
            # e.g. a line copied in Obsidian: give the copies new IDs right away,
            # otherwise one task is hidden and edits hit the wrong line (B-34).
            if _write(user, [{"op": "ensure_ids"}]) is not None:
                text = _read_note(user)
    except TaskSyncError as error:
        return {"status": "error", "error": str(error)}
    except VaultError as error:
        _record_error(user, error.message)
        return {"status": "offline" if error.kind == "offline" else "error", "error": error.message}
    _cache_from_note(user, text or "")
    s.tasks_last_sync = timezone.now()
    s.tasks_sync_error = ""
    s.save(update_fields=["tasks_last_sync", "tasks_sync_error"])
    return {"status": "ok", "synced_at": s.tasks_last_sync.isoformat(), "note_exists": text is not None}


def sync_tasks(user, force=False):
    """Refresh the cache from the note when stale (or ``force``)."""
    if not vault_configured(user):
        return {"status": "local"}
    s = _settings(user)
    interval = getattr(dj_settings, "TASKS_SYNC_INTERVAL", 60)
    if not force and s.tasks_last_sync and (timezone.now() - s.tasks_last_sync).total_seconds() < interval:
        return {"status": "fresh"}
    return _sync_now(user)


# --------------------------------------------------------------------------- writing

def add_task(user, text, due=None, priority=None, tags=None, status=None, section=None):
    from .models import Task
    if not vault_configured(user):
        return Task.objects.create(user=user, title=text, priority=priority or "medium", due_date=due or None,
                                   tags=", ".join(_tags_list(tags)), status=status or "todo")
    tags = tasks_md.validate_tags(_tags_list(tags))
    task_id = tasks_md.generate_id([])
    op = {"op": "add", "id": task_id, "text": text, "due": due or None, "priority": priority or None,
          "tags": tags, "status": status or "todo"}
    if section:
        op["section"] = section
    tasks_md.apply_op(tasks_md.new_tasks_note(), dict(op))   # validate before any write
    task = Task.objects.create(user=user, title=" ".join(str(text).split())[:255], priority=priority or "medium",
                               due_date=due or None, tags=", ".join(tags), status=status or "todo",
                               vault_id=task_id, synced=False)
    try:
        results = _write(user, [op])
    except TaskSyncError:
        task.delete()
        raise
    if results is not None:
        Task.objects.filter(pk=task.pk).update(synced=True)
        task.synced = True
    return task


_FIELD_MAP = {"title": "text", "due_date": "due", "priority": "priority", "tags": "tags", "status": "status"}


def update_task(user, task_pk, **fields):
    from .models import Task
    task = Task.objects.get(pk=task_pk, user=user)
    if not vault_configured(user) or (not task.vault_id and not task.vault_line):
        # Database-only task (no vault, or not exported yet): stays local.
        for key, value in fields.items():
            setattr(task, key, ", ".join(_tags_list(value)) if key == "tags" else value)
        task.save()
        return task
    op = {"op": "update"}
    if task.vault_id:
        op["id"] = task.vault_id
    else:
        op["line"] = task.vault_line
    for key, value in fields.items():
        if key not in _FIELD_MAP:
            continue
        if key == "tags":
            current = _tags_list(task.tags)
            value = list(dict.fromkeys(_tags_list(value)))
            if value == current:
                continue                   # unchanged (may contain tags written in Obsidian)
            tasks_md.validate_tags([t for t in value if t not in current])   # only new tags (B-35)
        elif key == "priority" and value == task.priority:
            continue                       # keeps "no priority" lines unchanged
        elif key == "due_date":
            value = str(value) if value else None
            if value == (str(task.due_date) if task.due_date else None):
                continue
        elif key == "title" and value == task.title:
            continue
        elif key == "status" and value == task.status:
            continue
        op[_FIELD_MAP[key]] = value
    if len(op) <= 2:
        return task
    for key, value in fields.items():
        if key in _FIELD_MAP:
            setattr(task, key, ", ".join(_tags_list(value)) if key == "tags" else (value or None if key == "due_date" else value))
    task.synced = False
    task.save()
    results = _write(user, [op])
    if results is None:
        return task
    info = results[0]
    if info.get("missing"):
        task.delete()
        sync_tasks(user, force=True)
        raise TaskSyncError(DELETED_ELSEWHERE)
    task.vault_id = info.get("id") or task.vault_id
    task.synced = True
    task.save(update_fields=["vault_id", "synced"])
    return task


def delete_task(user, task_pk):
    from .models import Task
    task = Task.objects.get(pk=task_pk, user=user)
    if not vault_configured(user) or (not task.vault_id and not task.vault_line):
        task.delete()
        return
    op = {"op": "delete", "id": task.vault_id} if task.vault_id else {"op": "delete", "line": task.vault_line}
    task.delete()
    _write(user, [op])            # a task already deleted elsewhere is simply gone


# --------------------------------------------------------------------------- export (old DB tasks → note)

def export_operations(user):
    """Add-operations for tasks that exist only in the database (never exported)."""
    from .models import Task
    ops, rows, dropped = [], [], []
    for task in Task.objects.filter(user=user, vault_id="", vault_line="").order_by("created_at", "id"):
        tags = []
        for tag in _tags_list(task.tags):
            (tags if tag in tasks_md.ALLOWED_TAGS else dropped).append(tag)
        status = task.status if task.status in tasks_md.MARK_BY_STATUS else "todo"
        ops.append({"op": "add", "id": tasks_md.generate_id([]), "text": task.title,
                    "due": task.due_date.isoformat() if task.due_date else None,
                    "priority": task.priority if task.priority in tasks_md.EMOJI_BY_PRIORITY else None,
                    "tags": tags, "status": status})
        rows.append(task)
    return ops, rows, sorted(set(dropped))


def export_preview(user):
    ops, rows, dropped = export_operations(user)
    text = _read_note(user) or tasks_md.new_tasks_note()
    text, _ = tasks_md.apply_op(text, {"op": "ensure_ids"})
    for op in ops:
        text, _ = tasks_md.apply_op(text, op)
    return text, len(ops), dropped


def export_to_note(user):
    from .models import Task
    ops, rows, dropped = export_operations(user)
    if not ops:
        return 0, dropped
    results = vault_apply(user, _note_operation(user, ops), f"tasks: import {len(ops)} task(s) from the site database")
    for row, op in zip(rows, ops):
        Task.objects.filter(pk=row.pk).update(vault_id=op["id"], synced=True)
    sync_tasks(user, force=True)
    return len(ops), dropped
