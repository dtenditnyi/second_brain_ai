"""Editing notes through the single vault writer (Round 4 / G-D2…D5).

Every change goes through ``vault_writer.vault_apply`` (lock → pull → operation →
commit "notes: … via site" → push, re-applied on a rejected push) and re-indexes
only the changed notes in Chroma. Only ``.md`` files inside the vault can be
written (attachments are read-only); ``.git/`` and ``.obsidian/`` never.

Conflicts: the editor sends the SHA-256 of the text it opened (``base_sha``). If
the file changed meanwhile, nothing is overwritten: ``NoteConflict`` carries the
current text and a diff. Offline saves go to ``VaultOutbox`` (kind "note"); when
they are flushed and the file changed meanwhile, the user's text is written to a
"(конфликт …)" copy next to the note — nothing is lost.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import hashlib
import logging
import os
import re
from pathlib import Path, PurePosixPath

from django.conf import settings as dj_settings
from django.utils import timezone

from . import tasks_md
from .vault_writer import UnsafePath, VaultError, safe_path, vault_apply, vault_read

logger = logging.getLogger("core.notes")

TEMPLATES_DIR = "99 - Templates"
MOC_DIR = "00 - Maps of content"
DEFAULT_MOC = "Главная (Home)"
SKIP_DIRS = {".git", ".obsidian", ".trash"}
_BAD_TITLE = re.compile(r'[\\/<>:"|?*\x00-\x1f#^\[\]]')


class NoteError(Exception):
    """Bad input or a missing/existing note (HTTP 400/404)."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


class NoteConflict(Exception):
    def __init__(self, current_content, current_sha, diff):
        super().__init__("Заметка изменилась после открытия.")
        self.current_content, self.current_sha, self.diff = current_content, current_sha, diff


def sha(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def diff_text(old, new, path="note.md"):
    return "".join(difflib.unified_diff(
        (old or "").splitlines(keepends=True), (new or "").splitlines(keepends=True),
        fromfile=f"a/{path}", tofile=f"b/{path}"))


def md_path(root, rel):
    """Validated absolute path of a Markdown note (attachments are read-only)."""
    if not isinstance(rel, str) or not rel.lower().endswith(".md"):
        raise NoteError("Изменять можно только заметки .md (вложения — только чтение).")
    try:
        return safe_path(root, rel)
    except UnsafePath as error:
        raise NoteError(str(error)) from None


def _norm(rel):
    return str(PurePosixPath(str(rel).replace("\\", "/")))


def _read(path):
    return path.read_bytes().decode("utf-8") if path.exists() else None


def _reindex(user, changed=(), removed=()):
    """Update the vector index for these notes only; never breaks a save."""
    try:
        from . import rag_engine
        rag_engine.reindex_notes(user, list(changed), list(removed))
    except Exception as error:  # pragma: no cover - logged, the note is saved anyway
        logger.warning("Re-index failed: %s.", type(error).__name__)


# --------------------------------------------------------------------------- listing

def _local_root(user):
    """The user's clone (pulled when missing), used for read-only listings."""
    from .paths import get_user_paths
    root = Path(get_user_paths(user)["notes_dir"])
    if not (root / ".git").exists():
        vault_read(user, lambda r: None)
    return root


def _walk_md(root):
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            if name.lower().endswith(".md"):
                full = Path(current) / name
                yield full.relative_to(root).as_posix(), full


def _aliases(text):
    match = re.match(r"---\r?\n(.*?)\r?\n---", text or "", re.S)
    if not match:
        return []
    body = match.group(1)
    inline = re.search(r"(?m)^aliases:\s*\[(.*?)\]\s*$", body)
    if inline:
        return [a.strip().strip("'\"") for a in inline.group(1).split(",") if a.strip()]
    block = re.search(r"(?m)^aliases:\s*\n((?:\s*-\s*.+\n?)+)", body)
    if block:
        return [line.strip()[1:].strip().strip("'\"") for line in block.group(1).splitlines() if line.strip()]
    return []


def note_names(user):
    root = _local_root(user)
    notes = []
    for rel, full in _walk_md(root):
        if rel.startswith(TEMPLATES_DIR + "/"):
            continue
        try:
            text = full.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            text = ""
        notes.append({"name": PurePosixPath(rel).stem, "path": rel, "aliases": _aliases(text)})
    return notes


def meta(user):
    root = _local_root(user)
    folders = [""]
    for current, dirs, _files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for d in dirs:
            folders.append((Path(current) / d).relative_to(root).as_posix())
    templates = sorted(PurePosixPath(rel).stem for rel, _ in _walk_md(root) if rel.startswith(TEMPLATES_DIR + "/"))
    mocs = sorted(PurePosixPath(rel).stem for rel, _ in _walk_md(root) if rel.startswith(MOC_DIR + "/"))
    return {"folders": sorted(set(folders)), "templates": templates, "mocs": mocs}


# --------------------------------------------------------------------------- read / save

def read_note(user, rel):
    rel = _norm(rel)

    def reader(root):
        path = md_path(root, rel) if rel.lower().endswith(".md") else None
        if path is None:
            raise NoteError("Открыть в редакторе можно только заметку .md.")
        text = _read(path)
        if text is None:
            raise NoteError("Заметка не найдена.", status=404)
        return {"path": rel, "content": text, "sha": sha(text)}

    return vault_read(user, reader)


def _save_operation(rel, content, base_sha):
    def operation(root):
        path = md_path(root, rel)
        current = _read(path)
        current_sha = sha(current) if current is not None else None
        if (base_sha or None) != current_sha:
            raise NoteConflict(current or "", current_sha, diff_text(current or "", content, rel))
        if current == content:
            return [], {"sha": current_sha}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
        return [rel], {"sha": sha(content)}
    return operation


def save_note(user, rel, content, base_sha, queue_offline=True):
    """Save the editor text. Raises NoteConflict / NoteError; offline → queued."""
    rel = _norm(rel)
    if not isinstance(content, str):
        raise NoteError("Текст заметки должен быть строкой.")
    md_path(Path("/tmp/vault-check"), rel)          # validate before touching git
    try:
        result = vault_apply(user, _save_operation(rel, content, base_sha), f"notes: edit {rel} via site")
    except VaultError as error:
        if error.kind == "offline" and queue_offline:
            from .models import VaultOutbox
            VaultOutbox.objects.create(user=user, kind="note", last_error=error.message[:500],
                                       op={"op": "save", "path": rel, "content": content, "base_sha": base_sha})
            return {"sha": base_sha, "queued": True}
        raise
    _reindex(user, changed=[rel])
    return {**result, "queued": False}


def flush_outbox(user):
    """Send queued offline note saves; a save whose base changed becomes a conflict copy."""
    from .models import VaultOutbox
    for row in VaultOutbox.objects.filter(user=user, kind="note").order_by("id"):
        op = row.op
        try:
            save_note(user, op["path"], op["content"], op.get("base_sha"), queue_offline=False)
        except NoteConflict:
            copy = _conflict_copy_path(op["path"])
            create_raw(user, copy, op["content"], f"notes: conflict copy of {op['path']} (offline edit)")
        except VaultError as error:
            if error.kind == "offline":
                VaultOutbox.objects.filter(pk=row.pk).update(attempts=row.attempts + 1, last_error=error.message[:500])
                return False
            raise
        row.delete()
    return True


def _conflict_copy_path(rel):
    p = PurePosixPath(rel)
    stamp = timezone.localtime().strftime("%Y-%m-%d %H%M")
    return str(p.with_name(f"{p.stem} (конфликт {stamp}){p.suffix}"))


def create_raw(user, rel, content, message):
    def operation(root):
        path = md_path(root, rel)
        if path.exists():
            raise NoteError("Такая заметка уже есть.")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))
        return [rel], rel
    result = vault_apply(user, operation, message)
    _reindex(user, changed=[rel])
    return result


# --------------------------------------------------------------------------- create

def _validate_title(title):
    title = " ".join(str(title or "").split())
    if not title or len(title) > 150 or _BAD_TITLE.search(title) or title.rstrip(" .") != title or title.startswith("."):
        raise NoteError("Недопустимое название заметки (без / \\ : * ? \" < > | # ^ [ ] и точки в конце).")
    return title


def _validate_folder(folder):
    folder = _norm(folder or "").strip("/")
    if folder in ("", "."):
        return ""
    for part in folder.split("/"):
        if part in ("", ".", "..") or part.casefold().rstrip(" .") in SKIP_DIRS or part.startswith("."):
            raise NoteError("Недопустимая папка.")
    return folder


_TP_DATE = re.compile(r"<%[-_]?\s*tp\.date\.now\(\s*(?:([\"'])(.*?)\1)?\s*\)\s*[-_]?%>")
_TP_TITLE = re.compile(r"<%[-_]?\s*tp\.file\.title\s*[-_]?%>")


def _format_moment(fmt, day):
    """Tiny subset of moment.js formats used in templates (YYYY, YY, MM, M, DD, D)."""
    if not fmt:
        return day.isoformat()
    tokens = {"YYYY": f"{day.year:04d}", "YY": f"{day.year % 100:02d}", "MM": f"{day.month:02d}",
              "DD": f"{day.day:02d}", "M": str(day.month), "D": str(day.day)}
    return re.sub(r"YYYY|YY|MM|DD|M|D", lambda m: tokens[m.group(0)], fmt)


def render_template(text, title, today):
    """Templater is NOT executed: only tp.date.now(...) and tp.file.title are filled in."""
    text = _TP_DATE.sub(lambda m: _format_moment(m.group(2), today), text)
    return _TP_TITLE.sub(title, text)


def default_note(title, tags, today, content="", moc=DEFAULT_MOC):
    tag_list = ", ".join(tags)
    body = (f"---\ntags: [{tag_list}]\ntype: note\nstatus: active\ndate: {today.isoformat()}\naliases: []\n---\n"
            f"# {title}\n\n")
    if content:
        body += content.rstrip() + "\n\n"
    return body + f"🔗 [[{moc or DEFAULT_MOC}]]\n"


def create_note(user, folder, title, template=None, tags=None, moc=None, content="", today=None):
    """Create ``<folder>/<title>.md`` (optionally from ``99 - Templates/<template>.md``)."""
    title = _validate_title(title)
    folder = _validate_folder(folder)
    tags = tasks_md.validate_tags(tags or [])
    today = today or timezone.localdate()
    rel = f"{folder}/{title}.md" if folder else f"{title}.md"
    if template:
        template = _validate_title(template)          # a plain file name inside 99 - Templates

    def operation(root):
        path = md_path(root, rel)
        if path.exists():
            raise NoteError("Такая заметка уже есть.")
        if template:
            tpl = md_path(root, f"{TEMPLATES_DIR}/{template}.md")
            source = _read(tpl)
            if source is None:
                raise NoteError("Шаблон не найден.", status=404)
            text = render_template(source, title, today)
            if content:
                text = text.rstrip("\n") + "\n\n" + content.rstrip() + "\n"
            if moc:
                text = text.rstrip("\n") + f"\n\n🔗 [[{moc}]]\n"
        else:
            text = default_note(title, tags, today, content, moc or DEFAULT_MOC)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return [rel], rel

    result = vault_apply(user, operation, f"notes: create {rel} via site")
    _reindex(user, changed=[rel])
    return result


# --------------------------------------------------------------------------- append (agent/API)

def append_to_note(user, rel, text, message=None):
    rel = _norm(rel)
    if not isinstance(text, str) or not text.strip():
        raise NoteError("Пустой текст.")

    def operation(root):
        path = md_path(root, rel)
        current = _read(path)
        if current is None:
            raise NoteError("Заметка не найдена.", status=404)
        new = current if current.endswith("\n") or not current else current + "\n"
        new += text.rstrip("\n") + "\n"
        path.write_bytes(new.encode("utf-8"))
        return [rel], rel

    result = vault_apply(user, operation, message or f"notes: append to {rel} via site")
    _reindex(user, changed=[rel])
    return result


# --------------------------------------------------------------------------- delete / rename

def delete_note(user, rel):
    rel = _norm(rel)
    md_path(Path("/tmp/vault-check"), rel)

    def operation(root):
        path = md_path(root, rel)
        if not path.exists():
            raise NoteError("Заметка не найдена.", status=404)
        path.unlink()
        return [rel], rel

    result = vault_apply(user, operation, f"notes: delete {rel} via site")
    _reindex(user, removed=[rel])
    return result


def _link_pattern(targets):
    alternatives = "|".join(re.escape(t) for t in sorted(targets, key=len, reverse=True))
    return re.compile(r"(!?\[\[)(" + alternatives + r")((?:#[^\]|\n]*)?(?:\|[^\]\n]*)?\]\])", re.IGNORECASE)


def _relink(text, old_rel, new_rel, bare_names=True):
    """Rewrite links to the renamed note. Links match case-insensitively like Obsidian; bare
    ``[[Name]]`` links are rewritten only when no other note has that name (VERIFY M5)."""
    old, new = PurePosixPath(old_rel), PurePosixPath(new_rel)
    old_path, new_path = str(old.with_suffix("")), str(new.with_suffix(""))
    by_target = {old_path: new_path, old_path + ".md": new_path + ".md"}
    if bare_names:
        by_target.update({old.stem: new.stem, old.name: new.name})
    lookup = {k.casefold(): v for k, v in by_target.items()}
    pattern = _link_pattern(by_target)
    return pattern.sub(lambda m: m.group(1) + lookup[m.group(2).casefold()] + m.group(3), text)


def _rename_plan(root, rel, new_rel):
    src, dst = md_path(root, rel), md_path(root, new_rel)
    if not src.exists():
        raise NoteError("Заметка не найдена.", status=404)
    if dst.exists():
        raise NoteError("Заметка с таким именем уже есть.")
    updates = {}
    files = list(_walk_md(root))
    stem = PurePosixPath(rel).stem.casefold()
    unique = sum(1 for other, _ in files if PurePosixPath(other).stem.casefold() == stem) <= 1
    for other, full in files:
        text = full.read_bytes().decode("utf-8")          # byte-exact: CRLF notes stay CRLF (VERIFY M4)
        new_text = _relink(text, rel, new_rel, bare_names=unique)
        if new_text != text:
            updates[other] = new_text
    return src, dst, updates


def rename_note(user, rel, new_rel, preview=False):
    rel, new_rel = _norm(rel), _norm(new_rel)
    for r in (rel, new_rel):
        md_path(Path("/tmp/vault-check"), r)
    if preview:
        def reader(root):
            _, _, updates = _rename_plan(root, rel, new_rel)
            return {"path": new_rel, "affected": sorted(new_rel if p == rel else p for p in updates)}
        return vault_read(user, reader)

    def operation(root):
        src, dst, updates = _rename_plan(root, rel, new_rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        changed = [rel, new_rel]
        for other, text in updates.items():
            target = new_rel if other == rel else other
            md_path(root, target).write_bytes(text.encode("utf-8"))
            changed.append(target)
        return sorted(set(changed)), {"path": new_rel, "updated": sorted(set(new_rel if p == rel else p for p in updates))}

    result = vault_apply(user, operation, f"notes: rename {rel} → {new_rel} via site")
    _reindex(user, changed=[new_rel, *[p for p in result["updated"] if p != new_rel]], removed=[rel])
    return result


# --------------------------------------------------------------------------- task checkbox (Round 5, F2)

TASK_CHARS = {"todo": " ", "done": "x", "in_progress": "/", "forwarded": ">", "cancelled": "-",
              " ": " ", "x": "x", "/": "/", ">": ">", "-": "-"}
_TASK_LINE = re.compile(r"^(\s*[-*+] )\[(.)\]( .*)$")


def set_task_status(user, rel, raw_line, status, line_no=None):
    """Change ``[c]`` of exactly this task line (matched by its text; ``line_no`` breaks ties).

    The line must still be what the page showed — otherwise NoteConflict-like 409 (reload).
    """
    rel = _norm(rel)
    char = TASK_CHARS.get(status)
    if char is None:
        raise NoteError("Неизвестный статус задачи.")
    if not isinstance(raw_line, str) or not _TASK_LINE.match(raw_line.rstrip("\r")):
        raise NoteError("Это не строка задачи.")
    raw_line = raw_line.rstrip("\r")

    def operation(root):
        path = md_path(root, rel)
        text = _read(path)
        if text is None:
            raise NoteError("Заметка не найдена.", status=404)
        lines = text.split("\n")
        bare = [l.rstrip("\r") for l in lines]
        hits = [i for i, l in enumerate(bare) if l == raw_line]
        if not hits:
            raise NoteError("Задача изменилась в другом месте — обновите заметку.", status=409)
        index = line_no if isinstance(line_no, int) and line_no in hits else hits[0]
        match = _TASK_LINE.match(bare[index])
        if match.group(2) == char:
            return [], {"path": rel, "line": index, "status": status, "changed": False}
        ending = "\r" if lines[index].endswith("\r") else ""
        lines[index] = f"{match.group(1)}[{char}]{match.group(3)}{ending}"
        path.write_bytes("\n".join(lines).encode("utf-8"))
        return [rel], {"path": rel, "line": index, "status": status, "changed": True,
                       "raw": lines[index].rstrip("\r")}

    result = vault_apply(user, operation, f"notes: task status in {rel} via site")
    if result.get("changed"):
        _reindex(user, changed=[rel])
    return result
