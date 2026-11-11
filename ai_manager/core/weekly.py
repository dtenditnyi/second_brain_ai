"""Weekly notes (06 - Daily) — Round 4: find the current week's note for quick capture.

Rule (DECISIONS D26): the current weekly note is the note under ``WEEKLY_ROOT`` whose
frontmatter has ``type: weekly`` and the latest ``date:`` that is not in the future (the
most recent week the owner started). Round 5 adds creating this week's note by Template_Weekly.
"""
from __future__ import annotations

import datetime as _dt
import re

from django.conf import settings as dj_settings
from django.utils import timezone

from . import notes_service

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---", re.S)


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


def weekly_notes(user):
    root = notes_service._local_root(user)
    prefix = getattr(dj_settings, "WEEKLY_ROOT", "06 - Daily").rstrip("/") + "/"
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


def current_week_note(user, today=None):
    today = today or timezone.localdate()
    candidates = [(start, rel) for start, rel in weekly_notes(user) if start <= today]
    if not candidates:
        return None
    return candidates[-1][1]
