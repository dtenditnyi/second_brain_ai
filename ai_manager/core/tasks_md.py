"""Lossless parser / serializer for the Obsidian tasks note (Round 3 / G-C1, G-C2).

Pure Python, no Django: the Telegram bot (or any other client) can reuse it.
Contract: ``docs/TASKS_FORMAT.md``.

* ``parse(text)`` keeps every line verbatim (line endings included), so
  ``serialize(parse(text)) == text`` for any input.
* Only a task that an operation changes is re-rendered; every other byte of
  the note (prose, Dataview blocks, sub-tasks, unknown markers) is untouched.
* Task lines follow the Obsidian Tasks / Dataview emoji format::

      - [ ] Сдать лабу по физике 📅 2026-11-14 ⏫ #university ➕ 2026-11-11 🆔 t7k2m9
"""
from __future__ import annotations

import datetime as _dt
import re
import secrets
from dataclasses import dataclass, field

ALLOWED_TAGS = (
    "university", "dsa", "physics", "databases", "economics", "electronics", "romanian", "nuclear", "dev",
    "ai", "homelab", "driving", "cooking", "sport", "health", "finance", "planning", "games", "books",
    "personal", "obsidian",
)

STATUS_BY_MARK = {" ": "todo", "/": "in_progress", "x": "done", "X": "done", "-": "cancelled", ">": "forwarded"}
MARK_BY_STATUS = {"todo": " ", "in_progress": "/", "done": "x", "cancelled": "-", "forwarded": ">"}
PRIORITY_BY_EMOJI = {"🔺": "urgent", "⏫": "high", "🔼": "medium", "🔽": "low", "⏬": "low"}
EMOJI_BY_PRIORITY = {"urgent": "🔺", "high": "⏫", "medium": "🔼", "low": "🔽"}
DEFAULT_SECTION = "📥 Входящие"
MOC_LINE = "🔗 [[Главная (Home)]]"
ID_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789"

_TASK_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<bullet>[-*+]|\d+[.)]) \[(?P<mark>[^\]\r\n])\](?P<body>(?: .*)?)$")
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
_SIGNIFIERS = "📅⏳🛫➕✅❌🆔⛔🔁🔺⏫🔼🔽⏬"
_DATE = r"\d{4}-\d{2}-\d{2}"
_FIELD_RES = {
    "due": re.compile(rf"📅️?\s*({_DATE})"),
    "created": re.compile(rf"➕️?\s*({_DATE})"),
    "done": re.compile(rf"✅️?\s*({_DATE})"),
    "cancelled_on": re.compile(rf"❌️?\s*({_DATE})"),
    "id": re.compile(r"🆔️?\s*([A-Za-z0-9_-]+)"),
}
_PRIORITY_RE = re.compile("(" + "|".join(map(re.escape, PRIORITY_BY_EMOJI)) + ")️?")
# "#tag" — not inside words/URLs/entities and not "[[#Heading]]" / "[[Note|#x]]" links (B-35).
_TAG_RE = re.compile(r"(?<![\w&#/\[|])#([\w/-]*[^\W\d_][\w/-]*)")
_EOL_RE = re.compile(r"(\r\n|\n|\r)$")


class TaskNotFound(KeyError):
    """The task (by ID) is not in the note — e.g. it was deleted in Obsidian."""


@dataclass
class TaskLine:
    index: int                      # position in TaskNote.lines
    indent: str
    bullet: str
    mark: str
    raw: str                        # line without its line ending
    eol: str
    section: str | None
    text: str = ""
    due: str | None = None
    created: str | None = None
    done: str | None = None
    cancelled_on: str | None = None
    priority: str | None = None
    priority_emoji: str | None = None
    tags: list = field(default_factory=list)
    id: str | None = None
    extra: str = ""                 # unknown metadata (⏳, 🛫, 🔁 …), kept verbatim

    @property
    def status(self) -> str:
        return STATUS_BY_MARK.get(self.mark, "todo")

    @property
    def is_subtask(self) -> bool:
        return bool(self.indent)


@dataclass
class TaskNote:
    lines: list                     # str lines WITH their line endings
    tasks: list

    def by_id(self, task_id):
        for task in self.tasks:
            if task.id == task_id:
                return task
        raise TaskNotFound(task_id)


def _split_lines(text):
    return text.splitlines(keepends=True) if text else []


def _parse_body(task: TaskLine, body: str):
    body = body[1:] if body.startswith(" ") else body
    positions = [i for i, ch in enumerate(body) if ch in _SIGNIFIERS]
    cut = positions[0] if positions else len(body)
    description, rest = body[:cut], body[cut:]
    for name, regex in _FIELD_RES.items():
        match = regex.search(rest)
        if match:
            setattr(task, name, match.group(1))
            rest = rest[:match.start()] + " " + rest[match.end():]
    match = _PRIORITY_RE.search(rest)
    if match:
        task.priority_emoji = match.group(1)
        task.priority = PRIORITY_BY_EMOJI[match.group(1)]
        rest = rest[:match.start()] + " " + rest[match.end():]
    rest_tags = _TAG_RE.findall(rest)
    rest = _TAG_RE.sub(" ", rest)
    # Trailing #tags of the description belong to the metadata ("Купить #books").
    words = description.rstrip().split(" ")
    trailing = []
    while words and _TAG_RE.fullmatch(words[-1] or ""):
        trailing.insert(0, words.pop()[1:])
    task.text = " ".join(words).strip()
    inline = _TAG_RE.findall(task.text)
    seen = []
    for tag in inline + trailing + rest_tags:
        if tag not in seen:
            seen.append(tag)
    task.tags = seen
    task.extra = " ".join(rest.split())


def parse(text: str) -> TaskNote:
    lines = _split_lines(text)
    tasks, section = [], None
    fence = None                      # opening fence ("```", "````", "~~~"…) while inside a code block
    # Frontmatter only when the opening "---" is really closed later (B-45): an
    # unclosed "---" (e.g. a horizontal rule at the top) must not hide the tasks.
    in_frontmatter = bool(lines) and lines[0].rstrip("\r\n") == "---" and any(
        line.rstrip("\r\n").rstrip() in ("---", "...") for line in lines[1:])
    for index, line in enumerate(lines):
        eol_match = _EOL_RE.search(line)
        eol = eol_match.group(1) if eol_match else ""
        content = line[: len(line) - len(eol)]
        stripped = content.lstrip()
        if in_frontmatter:
            # YAML frontmatter: "# comment" lines are not headings, "- [ ]" not tasks (B-41)
            if index > 0 and content.rstrip() in ("---", "..."):
                in_frontmatter = False
            continue
        marker = re.match(r"(`{3,}|~{3,})", stripped)
        if marker:
            # A fence closes only with the same character and at least the same length (B-41).
            if fence is None:
                fence = marker.group(1)
            elif marker.group(1)[0] == fence[0] and len(marker.group(1)) >= len(fence) \
                    and not stripped[len(marker.group(1)):].strip():
                fence = None
            continue
        if fence is not None:
            continue
        heading = _HEADING_RE.match(content)
        if heading:
            section = heading.group(2).strip()
            continue
        match = _TASK_RE.match(content)
        if not match:
            continue
        task = TaskLine(index=index, indent=match.group("indent"), bullet=match.group("bullet"),
                        mark=match.group("mark"), raw=content, eol=eol, section=section)
        _parse_body(task, match.group("body") or "")
        tasks.append(task)
    return TaskNote(lines=lines, tasks=tasks)


def serialize(note: TaskNote) -> str:
    return "".join(note.lines)


def render(task: TaskLine) -> str:
    """Canonical line for a (changed) task, without line ending."""
    parts = [task.text.strip()] if task.text.strip() else []
    if task.due:
        parts.append(f"📅 {task.due}")
    if task.priority:
        emoji = task.priority_emoji if PRIORITY_BY_EMOJI.get(task.priority_emoji or "") == task.priority else None
        parts.append(emoji or EMOJI_BY_PRIORITY[task.priority])
    text_tags = set(_TAG_RE.findall(task.text))
    parts.extend(f"#{tag}" for tag in task.tags if tag not in text_tags)
    if task.created:
        parts.append(f"➕ {task.created}")
    if task.done and task.status == "done":
        parts.append(f"✅ {task.done}")
    if task.cancelled_on and task.status == "cancelled":
        parts.append(f"❌ {task.cancelled_on}")
    if task.extra:
        parts.append(task.extra)
    if task.id:
        parts.append(f"🆔 {task.id}")
    return f"{task.indent}{task.bullet} [{task.mark}] " + " ".join(parts)


def generate_id(existing) -> str:
    existing = set(existing)
    while True:
        candidate = "".join(secrets.choice(ID_ALPHABET) for _ in range(6))
        if candidate not in existing:
            return candidate


def validate_tags(tags):
    clean = []
    for tag in tags or []:
        tag = str(tag).strip().lstrip("#").strip()
        if not tag:
            continue
        if tag not in ALLOWED_TAGS:
            raise ValueError(f"Тег «{tag}» не разрешён. Разрешены: {', '.join(ALLOWED_TAGS)}.")
        if tag not in clean:
            clean.append(tag)
    return clean


def _validate_date(value):
    if value in (None, ""):
        return None
    _dt.date.fromisoformat(str(value))
    return str(value)


def _validate_text(value):
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    if not text:
        raise ValueError("Текст задачи не может быть пустым.")
    if any(ch in text for ch in _SIGNIFIERS):
        raise ValueError("Текст задачи не должен содержать служебные эмодзи (📅 ⏫ 🆔 …).")
    if len(text) > 500:
        raise ValueError("Текст задачи слишком длинный (максимум 500 символов).")
    return text


def _line_ending(note: TaskNote):
    for line in note.lines:
        if line.endswith("\r\n"):
            return "\r\n"
        if line.endswith("\n"):
            return "\n"
    return "\n"


def _insert_index(note: TaskNote, section: str, eol: str):
    """Line index for a new task in ``section``; creates the heading when missing.

    New tasks go after the last task (or its indented sub-items) of the section,
    or right under the heading when the section has no tasks yet.
    """
    lines = note.lines
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += eol
    heading_at = None
    for i, line in enumerate(lines):
        match = _HEADING_RE.match(line.rstrip("\r\n"))
        if match and match.group(2).strip() == section:
            heading_at = i
            break
    if heading_at is None:
        at, last = len(lines), len(lines) - 1
        while last >= 0 and not lines[last].strip():
            last -= 1
        if last >= 0 and lines[last].strip().startswith("🔗"):
            at = last
        block = [eol] if at > 0 and lines[at - 1].strip() else []
        block.append(f"## {section}{eol}")
        lines[at:at] = block + ([eol] if at < len(lines) else [])
        return at + len(block)
    insert, seen = heading_at + 1, False
    for i in range(heading_at + 1, len(lines)):
        content = lines[i].rstrip("\r\n")
        if _HEADING_RE.match(content):
            break
        if _TASK_RE.match(content) or (seen and content[:1] in (" ", "\t") and content.strip()):
            insert, seen = i + 1, True
        elif seen and not content.strip():
            break
    return insert


def _all_ids(note: TaskNote):
    return [t.id for t in note.tasks if t.id]


def _find(note: TaskNote, op):
    if op.get("id"):
        return note.by_id(op["id"])
    if op.get("line") is not None:
        for task in note.tasks:
            if task.raw == op["line"] or task.raw.strip() == str(op["line"]).strip():
                return task
    raise TaskNotFound(op.get("id") or op.get("line"))


def _set_status(task: TaskLine, status: str, today: str):
    if status not in MARK_BY_STATUS:
        raise ValueError(f"Неизвестный статус: {status}")
    task.mark = MARK_BY_STATUS[status]
    if status == "done":
        task.done = task.done or today
    elif status == "cancelled":
        task.cancelled_on = task.cancelled_on or today


def apply_op(text: str, op: dict, today: _dt.date | None = None):
    """Apply one operation to the note text and return ``(new_text, info)``.

    Operations (all by stable 🆔; ``line`` = exact raw line for tasks without an ID):
      {"op": "add", "text", "due"?, "priority"?, "tags"?, "status"?, "section"?, "id"?}
      {"op": "update", "id" | "line", "text"?, "due"?, "priority"?, "tags"?, "status"?}
      {"op": "delete", "id" | "line"}
      {"op": "ensure_ids"}   — give every task a unique ID (duplicates get a new one)
    ``info`` contains the affected task ``id`` (and ``changed`` for ensure_ids).
    Raises ``TaskNotFound`` / ``ValueError``.
    """
    today_s = (today or _dt.date.today()).isoformat()
    note = parse(text)
    eol = _line_ending(note)
    kind = op.get("op")
    if kind not in ("add", "update", "delete", "ensure_ids"):
        raise ValueError(f"Неизвестная операция: {kind}")

    if kind == "ensure_ids":
        seen, changed = set(), 0
        existing = set(_all_ids(note))
        for task in note.tasks:
            if task.id and task.id not in seen:
                seen.add(task.id)
                continue
            task.id = generate_id(existing | seen)
            seen.add(task.id)
            note.lines[task.index] = render(task) + task.eol
            changed += 1
        return serialize(note), {"changed": changed}

    if kind == "add":
        new = TaskLine(index=-1, indent="", bullet="-", mark=" ", raw="", eol=eol, section=None)
        new.text = _validate_text(op.get("text"))
        new.due = _validate_date(op.get("due"))
        new.priority = op.get("priority") or None
        if new.priority and new.priority not in EMOJI_BY_PRIORITY:
            raise ValueError(f"Неизвестный приоритет: {new.priority}")
        new.tags = validate_tags(op.get("tags"))
        new.created = today_s
        new.id = op.get("id") or generate_id(_all_ids(note))
        if new.id in _all_ids(note):
            return text, {"id": new.id, "duplicate": True}   # replayed operation: already applied
        _set_status(new, op.get("status") or "todo", today_s)
        at = _insert_index(note, op.get("section") or DEFAULT_SECTION, eol)
        note.lines.insert(at, render(new) + eol)
        return serialize(note), {"id": new.id}

    task = _find(note, op)
    if kind == "delete":
        # Sub-items indented under the task go with it; left alone they would turn
        # into an indented (code) block under the heading (B-41).
        end = task.index + 1
        own = len(task.indent.expandtabs(4))
        def deeper(line):
            content = line.rstrip("\r\n")
            indent = len(content) - len(content.lstrip(" \t"))
            return bool(content.strip()) and len(content[:indent].expandtabs(4)) > own

        while end < len(note.lines):
            if deeper(note.lines[end]):
                end += 1
                continue
            # Blank lines inside the sub-item block belong to it when deeper lines follow (B-48).
            look = end
            while look < len(note.lines) and not note.lines[look].strip():
                look += 1
            if look > end and look < len(note.lines) and deeper(note.lines[look]):
                end = look
                continue
            break
        del note.lines[task.index:end]
        return serialize(note), {"id": task.id}
    if kind != "update":
        raise ValueError(f"Неизвестная операция: {kind}")
    if "text" in op and op["text"] is not None:
        task.text = _validate_text(op["text"])
    if "due" in op:
        task.due = _validate_date(op["due"])
    if "priority" in op:
        priority = op["priority"] or None
        if priority and priority not in EMOJI_BY_PRIORITY:
            raise ValueError(f"Неизвестный приоритет: {priority}")
        task.priority = priority
    if "tags" in op and op["tags"] is not None:
        # Tags already on the line may stay even if not in the allowed list (written
        # in Obsidian); only newly added ones are validated (B-35).
        kept = [str(t).strip().lstrip("#") for t in op["tags"] if str(t).strip().lstrip("#") in task.tags]
        added = validate_tags([t for t in op["tags"] if str(t).strip().lstrip("#") not in task.tags])
        task.tags = list(dict.fromkeys(kept + added))
        task.text = " ".join(w for w in task.text.split(" ") if not _TAG_RE.fullmatch(w) or w[1:] in task.tags)
    if op.get("status"):
        _set_status(task, op["status"], today_s)
    if not task.id and op.get("assign_id", True):
        task.id = generate_id(_all_ids(note))
    note.lines[task.index] = render(task) + task.eol
    return serialize(note), {"id": task.id}


def new_tasks_note(today: _dt.date | None = None, eol: str = "\n") -> str:
    """Body of a freshly created tasks note (frontmatter, sections, MOC link)."""
    date = (today or _dt.date.today()).isoformat()
    lines = [
        "---", "tags: [planning]", "type: tasks-db", "status: active", f"date: {date}",
        "aliases: [Задачи, Tasks]", "---", "# 🎯 Задачи", "",
        "> [!info] Задачи сайта Second Brain",
        "> Одна строка — одна задача. Сайт и бот меняют только строки задач, остальной текст не трогают.",
        "", f"## {DEFAULT_SECTION}", "", "## 🔥 Срочно", "", "## ✅ Выполнено", "", MOC_LINE,
    ]
    return eol.join(lines) + eol
