"""Weekly notes (06 - Daily): find, create («Эта неделя»), carry over tasks, calendar.

Rule for the current note (DECISIONS D26): the note under ``WEEKLY_ROOT`` whose frontmatter has
``type: weekly`` and the latest ``date:`` that is not in the future.

Creating this week's note (Round 5, DECISIONS D30): the naming rule is derived from the latest
existing weekly note — same folder (semester), same name pattern («Fifth week of 2nd year» →
«Seventh week of 2nd year», «Week 5» → «Week 7»), the number advanced by the number of
calendar weeks (Mondays) between that note's date and today. A ``week_type: A|B`` field (study
weeks A/B) alternates with odd differences. The body comes from ``99 - Templates/Template_Weekly``
(Templater is not executed: only ``tp.date.now`` / ``tp.file.title`` are filled in), with
``type: weekly`` and ``date:`` (this week's Monday) set in the frontmatter.
Without any weekly note yet: ``<WEEKLY_ROOT>/<year> by weeks/Week <ISO week>.md``.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import PurePosixPath

from django.conf import settings as dj_settings
from django.utils import timezone

from . import frontmatter as fm_mod
from . import notes_service, vault_index
from .vault_writer import vault_apply, vault_read

TEMPLATE_NAME = "Template_Weekly"
_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)
ORDINALS = ["Zeroth", "First", "Second", "Third", "Fourth", "Fifth", "Sixth", "Seventh", "Eighth", "Ninth",
            "Tenth", "Eleventh", "Twelfth", "Thirteenth", "Fourteenth", "Fifteenth", "Sixteenth",
            "Seventeenth", "Eighteenth", "Nineteenth", "Twentieth"]
_ORD_INDEX = {w.lower(): i for i, w in enumerate(ORDINALS)}
_PATTERNS = [
    (re.compile(r"^(?P<num>[A-Za-z]+)(?P<rest> week\b.*)$", re.I), "word"),
    (re.compile(r"^(?P<num>\d+)(?:st|nd|rd|th)(?P<rest> week\b.*)$", re.I), "suffix"),
    (re.compile(r"^(?P<pre>.*?\bweek\s+)(?P<num>\d+)(?P<rest>.*)$", re.I), "plain"),
    (re.compile(r"^(?P<pre>.*?\bнеделя\s+)(?P<num>\d+)(?P<rest>.*)$", re.I), "plain"),
]
CARRY_HEADING = "## ↪️ Перенесено с прошлой недели"
OPEN_CHARS = (" ", "/")


class WeeklyError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def frontmatter(text):
    match = _FM.match(text or "")
    if not match:
        return {}
    data = {}
    for line in match.group(1).splitlines():
        if ":" in line and not line.startswith((" ", "\t", "-")):
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip()
    return data


def _prefix():
    return getattr(dj_settings, "WEEKLY_ROOT", "06 - Daily").rstrip("/") + "/"


def weekly_notes_in(root):
    prefix = _prefix()
    notes = []
    for rel, full in notes_service._walk_md(root):
        if not rel.startswith(prefix):
            continue
        meta = frontmatter(full.read_text(encoding="utf-8", errors="replace"))
        if meta.get("type") != "weekly":
            continue
        try:
            start = _dt.date.fromisoformat(meta.get("date", "")[:10])
        except ValueError:
            continue
        notes.append((start, rel))
    return sorted(notes)


def weekly_notes(user):
    return weekly_notes_in(notes_service._local_root(user))


def current_week_note(user, today=None):
    today = today or timezone.localdate()
    candidates = [(start, rel) for start, rel in weekly_notes(user) if start <= today]
    if not candidates:
        return None
    return candidates[-1][1]


def monday(day):
    return day - _dt.timedelta(days=day.weekday())


def _ordinal_word(n):
    return ORDINALS[n] if 0 < n < len(ORDINALS) else _suffix(n)


def _suffix(n):
    tail = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{tail}"


def next_name(previous_name, weeks_ahead):
    """Advance the week number in ``previous_name`` by ``weeks_ahead`` keeping its style."""
    for pattern, style in _PATTERNS:
        match = pattern.match(previous_name)
        if not match:
            continue
        raw = match.group("num")
        if style == "word":
            if raw.lower() not in _ORD_INDEX:
                continue
            number = _ORD_INDEX[raw.lower()] + weeks_ahead
            word = _ordinal_word(number)
            return (word if raw[0].isupper() else word.lower()) + match.group("rest")
        if style == "suffix":
            return _suffix(int(raw) + weeks_ahead) + match.group("rest")
        return match.group("pre") + str(int(raw) + weeks_ahead) + match.group("rest")
    return None


def plan_this_week(root, today):
    """(rel, created_needed, previous_rel) for the week containing ``today``."""
    start = monday(today)
    notes = weekly_notes_in(root)
    for day, rel in reversed(notes):
        if monday(day) == start:
            return rel, False, None
    past = [(d, r) for d, r in notes if monday(d) < start]
    if past:
        day, prev = past[-1]
        ahead = (start - monday(day)).days // 7
        name = next_name(PurePosixPath(prev).stem, ahead) or f"Week {today.isocalendar()[1]}"
        folder = str(PurePosixPath(prev).parent)
        return f"{folder}/{name}.md", True, prev
    year = today.year
    return f"{_prefix()}{year} by weeks/Week {today.isocalendar()[1]}.md", True, None


def _week_text(root, rel, title, today, previous_meta):
    tpl = notes_service.md_path(root, f"{notes_service.TEMPLATES_DIR}/{TEMPLATE_NAME}.md")
    source = notes_service._read(tpl)
    start = monday(today)
    if source is None:
        source = (f"---\ntags: [planning]\ntype: weekly\ndate: {start.isoformat()}\n---\n# {title}\n\n"
                  f"## 🎯 Цели недели\n- [ ] \n\n🔗 [[{notes_service.DEFAULT_MOC}]]\n")
    text = notes_service.render_template(source, title, start)
    fields = {"type": "weekly", "date": start.isoformat()}
    wt = (previous_meta or {}).get("week_type", "").strip().upper()
    if wt in ("A", "B") and previous_meta.get("_ahead") is not None:
        fields["week_type"] = wt if previous_meta["_ahead"] % 2 == 0 else ("B" if wt == "A" else "A")
    if fm_mod.split(text) is None:
        text = "---\ntype: weekly\n---\n" + text
    return fm_mod.set_fields(text, fields)


def this_week(user, today=None):
    """Open or create this week's note. Returns {"path", "created", "name"}."""
    today = today or timezone.localdate()
    found = vault_read(user, lambda root: plan_this_week(root, today))
    if not found[1]:
        return {"path": found[0], "created": False, "name": PurePosixPath(found[0]).stem}

    def operation(root):
        rel, needed, prev = plan_this_week(root, today)
        if not needed:
            return [], {"path": rel, "created": False}
        path = notes_service.md_path(root, rel)
        if path.exists():                     # same name, other date: open it, never overwrite
            return [], {"path": rel, "created": False}
        prev_meta = {}
        if prev:
            prev_meta = frontmatter(notes_service._read(notes_service.md_path(root, prev)) or "")
            prev_day = _dt.date.fromisoformat(prev_meta.get("date", "")[:10])
            prev_meta["_ahead"] = (monday(today) - monday(prev_day)).days // 7
        text = _week_text(root, rel, PurePosixPath(rel).stem, today, prev_meta)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
        return [rel], {"path": rel, "created": True}

    result = vault_apply(user, operation, "weekly: create this week's note via site")
    if result["created"]:
        notes_service._reindex(user, changed=[result["path"]])
    result["name"] = PurePosixPath(result["path"]).stem
    return result


# --------------------------------------------------------------------------- carry over

def _previous_of(root, target_rel):
    notes = weekly_notes_in(root)
    target = next((d for d, r in notes if r == target_rel), None)
    if target is None:
        raise WeeklyError("Это не недельная заметка (type: weekly, date).", 404)
    earlier = [r for d, r in notes if d < target and r != target_rel]
    if not earlier:
        raise WeeklyError("Нет прошлой недельной заметки.", 404)
    return earlier[-1]


def _open_tasks(text):
    """Top-level open tasks (``[ ]`` / ``[/]``) with their indented sub-lines, outside code."""
    lines = text.split("\n")
    out, fenced, i = [], False, 0
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        match = None if fenced else re.match(r"^([-*+]) \[(.)\] (.+)$", line)
        if match and match.group(2) in OPEN_CHARS:
            block = [i]
            j = i + 1
            while j < len(lines) and lines[j].startswith(("  ", "\t")) and lines[j].strip():
                block.append(j)
                j += 1
            out.append(block)
            i = j
            continue
        i += 1
    return out


def _insert_section(text, items):
    lines = text.rstrip("\n").split("\n")
    if CARRY_HEADING in lines:
        idx = lines.index(CARRY_HEADING) + 1
        while idx < len(lines) and lines[idx].strip():
            idx += 1
        lines[idx:idx] = items
    else:
        tail = len(lines)
        if tail and lines[-1].lstrip().startswith("🔗"):
            tail -= 1
            while tail and not lines[tail - 1].strip():
                tail -= 1
        block = ["", CARRY_HEADING, *items, ""]
        lines[tail:tail] = block if tail < len(lines) else block[:-1]
    return "\n".join(lines) + "\n"


def _carry_plan(root, target_rel):
    prev = _previous_of(root, target_rel)
    old = notes_service._read(notes_service.md_path(root, prev)) or ""
    new = notes_service._read(notes_service.md_path(root, target_rel))
    if new is None:
        raise WeeklyError("Недельная заметка не найдена.", 404)
    blocks = _open_tasks(old)
    old_lines = old.split("\n")
    present = {l.strip() for l in new.split("\n")}
    items = []
    for block in blocks:
        first = old_lines[block[0]]
        moved = re.sub(r"^([-*+]) \[.\] ", r"\1 [ ] ", first) if first[3] == "/" else first
        if moved.strip() not in present:
            items.extend([moved] + [old_lines[k] for k in block[1:]])
        old_lines[block[0]] = re.sub(r"^([-*+]) \[.\] ", r"\1 [>] ", first)
    new_old = "\n".join(old_lines)
    new_new = _insert_section(new, items) if items else new
    return prev, old, new_old, new, new_new, len(blocks)


def carry_over(user, target_rel, preview=False):
    target_rel = notes_service._norm(target_rel)
    if preview:
        def reader(root):
            prev, old, new_old, new, new_new, count = _carry_plan(root, target_rel)
            return {"from": prev, "to": target_rel, "count": count,
                    "diff": notes_service.diff_text(old, new_old, prev) + notes_service.diff_text(new, new_new, target_rel)}
        return vault_read(user, reader)

    def operation(root):
        prev, old, new_old, new, new_new, count = _carry_plan(root, target_rel)
        if not count:
            return [], {"from": prev, "to": target_rel, "count": 0, "diff": ""}
        notes_service.md_path(root, prev).write_bytes(new_old.encode("utf-8"))
        notes_service.md_path(root, target_rel).write_bytes(new_new.encode("utf-8"))
        return [prev, target_rel], {"from": prev, "to": target_rel, "count": count,
                                    "diff": notes_service.diff_text(old, new_old, prev)
                                    + notes_service.diff_text(new, new_new, target_rel)}

    result = vault_apply(user, operation, f"weekly: carry over open tasks to {target_rel}")
    if result["count"]:
        notes_service._reindex(user, changed=[result["from"], result["to"]])
    return result


# --------------------------------------------------------------------------- calendar

def calendar(user, today=None):
    today = today or timezone.localdate()
    weeks = []
    for start, rel in weekly_notes(user):
        weeks.append({"path": rel, "name": PurePosixPath(rel).stem, "date": start.isoformat(),
                      "week_start": monday(start).isoformat(), "iso_week": monday(start).isocalendar()[1],
                      "current": monday(start) == monday(today)})
    return {"today": today.isoformat(), "this_week_start": monday(today).isoformat(), "weeks": weeks}


def open_tasks_this_week(user, today=None):
    """Open tasks of the current weekly note (home dashboard)."""
    rel = current_week_note(user, today)
    if not rel:
        return None, []
    note = next((n for n in vault_index.notes_of(user) if n.path == rel), None)
    if note is None:
        return rel, []
    return rel, [t for t in note.tasks if t["char"] in OPEN_CHARS][:10]
