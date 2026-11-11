"""Read-only index of a user's vault (Round 5, F1/F2): search, tags, links, graph, tasks.

Everything here reads the user's local clone (no pull, no writes) and never leaves it:
the walker skips ``.git`` / ``.obsidian`` / ``.trash`` and only reads ``*.md`` files below the
root. The scan is cached per root and invalidated when any note's mtime/size changes.
"""
from __future__ import annotations

import datetime as _dt
import html
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import frontmatter as fm_mod
from . import notes_service

TEMPLATES_PREFIX = notes_service.TEMPLATES_DIR + "/"
WIKI_RE = re.compile(r"(!?)\[\[([^\[\]\n]+?)\]\]")
TASK_RE = re.compile(r"^(\s*)[-*+] \[(.)\] (.*)$")
INLINE_TAG_RE = re.compile(r"(?<![\w/#&])#([A-Za-zА-Яа-яЁё_][\w/-]*)")
FENCE_RE = re.compile(r"^(```|~~~)")
TASK_STATUS = {" ": "todo", "x": "done", "X": "done", "/": "in_progress", ">": "forwarded", "-": "cancelled"}
MAX_NOTE_BYTES = 2_000_000


@dataclass
class Note:
    path: str
    name: str
    folder: str
    text: str
    mtime: float
    size: int
    meta: dict = field(default_factory=dict)
    tags: list = field(default_factory=list)
    aliases: list = field(default_factory=list)
    links: list = field(default_factory=list)        # raw link targets (note part, without #heading / |alias)
    tasks: list = field(default_factory=list)        # dicts: line, text, status, char, raw

    @property
    def body(self):
        found = fm_mod.split(self.text)
        if not found:
            return self.text
        end = self.text.find("\n", found[2] + 1)
        return self.text[end + 1:] if end >= 0 else ""

    @property
    def modified(self):
        return _dt.datetime.fromtimestamp(self.mtime)


def link_target(raw):
    """``Note#Heading|text`` → ``Note`` (the part that names a note)."""
    return raw.split("|", 1)[0].split("#", 1)[0].strip()


def _strip_code(text):
    out, fenced = [], False
    for line in text.splitlines():
        if FENCE_RE.match(line.lstrip()):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else re.sub(r"`[^`\n]*`", "", line))
    return out


def parse_note(rel, text, mtime=0.0, size=0):
    meta = fm_mod.parse(text) or {}
    tags = [t for t in fm_mod.tags_of(meta)]
    aliases = meta.get("aliases") if isinstance(meta.get("aliases"), list) else (
        [meta["aliases"]] if isinstance(meta.get("aliases"), str) and meta.get("aliases") else [])
    found = fm_mod.split(text)
    body_start = 0
    if found:
        nl = text.find("\n", found[2] + 1)
        body_start = text[:nl + 1].count("\n") if nl >= 0 else text.count("\n") + 1
    lines = _strip_code(text)
    tasks, links = [], []
    for number, line in enumerate(lines):
        if number < body_start:
            continue
        for match in INLINE_TAG_RE.finditer(WIKI_RE.sub("", line)):
            tag = match.group(1).rstrip("/")
            if tag not in tags:
                tags.append(tag)
        for match in WIKI_RE.finditer(line):
            target = link_target(match.group(2))
            if target:
                links.append(target)
        task = TASK_RE.match(line)
        if task:
            tasks.append({"line": number, "char": task.group(2), "status": TASK_STATUS.get(task.group(2), "todo"),
                          "text": task.group(3).strip(), "raw": text.splitlines()[number], "indent": len(task.group(1))})
    pure = PurePosixPath(rel)
    folder = str(pure.parent) if str(pure.parent) != "." else ""
    return Note(path=rel, name=pure.stem, folder=folder, text=text, mtime=mtime, size=size, meta=meta,
                tags=tags, aliases=[str(a) for a in aliases if str(a).strip()], links=links, tasks=tasks)


_CACHE: dict = {}
_LOCK = threading.Lock()


def scan_root(root):
    root = Path(root)
    stats = []
    for rel, full in notes_service._walk_md(root):
        try:
            st = full.stat()
        except OSError:
            continue
        if st.st_size <= MAX_NOTE_BYTES:
            stats.append((rel, full, st.st_mtime, st.st_size))
    signature = tuple((rel, mtime, size) for rel, _f, mtime, size in stats)
    key = str(root.resolve())
    with _LOCK:
        cached = _CACHE.get(key)
        if cached and cached[0] == signature:
            return cached[1]
    notes = []
    for rel, full, mtime, size in stats:
        try:
            text = full.read_bytes().decode("utf-8", errors="replace")
        except OSError:
            continue
        notes.append(parse_note(rel, text, mtime, size))
    with _LOCK:
        _CACHE[key] = (signature, notes)
    return notes


def user_root(user):
    """The user's own vault folder: the git clone (cloned on first use) or, without a configured
    repository, the plain local folder (legacy uploads; may be empty)."""
    from .models import get_user_settings
    from .paths import get_user_paths
    local = Path(get_user_paths(user)["notes_dir"])
    if (local / ".git").exists() or not get_user_settings(user).github_repo_url:
        return local
    return Path(notes_service._local_root(user))


def notes_of(user, include_templates=False):
    notes = scan_root(user_root(user))
    return notes if include_templates else [n for n in notes if not n.path.startswith(TEMPLATES_PREFIX)]


def resolver(notes):
    """name / alias / path-without-.md (case-insensitive) → Note."""
    table = {}
    for note in notes:
        for key in (note.path[:-3], note.name, *note.aliases):
            table.setdefault(key.lower(), note)
    return lambda target: table.get((target or "").strip().lower()) or table.get(
        PurePosixPath((target or "").strip()).name.lower())


# --------------------------------------------------------------------------- search

def _snippet(text, terms, width=80):
    low = text.lower()
    pos = min((low.find(t) for t in terms if low.find(t) >= 0), default=0)
    start, end = max(0, pos - width), min(len(text), pos + width)
    chunk = text[start:end].replace("\n", " ")
    escaped = html.escape(chunk)
    for term in sorted(set(terms), key=len, reverse=True):
        escaped = re.sub(re.escape(html.escape(term)), lambda m: f"<mark>{m.group(0)}</mark>", escaped, flags=re.I)
    return ("…" if start else "") + escaped + ("…" if end < len(text) else "")


def _parse_date(value):
    try:
        return _dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def search(user, q="", folder="", tag="", modified_after=None, modified_before=None, limit=50):
    terms = [t.lower() for t in (q or "").split() if t.strip()]
    folder = (folder or "").strip().strip("/")
    tag = (tag or "").strip().lstrip("#").lower()
    after, before = _parse_date(modified_after), _parse_date(modified_before)
    results = []
    for note in notes_of(user):
        if folder and not (note.path.startswith(folder + "/")):
            continue
        if tag and tag not in [t.lower() for t in note.tags]:
            continue
        day = note.modified.date()
        if (after and day < after) or (before and day > before):
            continue
        haystack = (note.name + "\n" + note.text).lower()
        if terms and not all(t in haystack for t in terms):
            continue
        score = sum(note.name.lower().count(t) * 10 + haystack.count(t) for t in terms)
        results.append((score, note.mtime, note))
    results.sort(key=lambda r: (-r[0], -r[1]))
    return [{"path": n.path, "name": n.name, "folder": n.folder, "tags": n.tags,
             "modified": n.modified.isoformat(timespec="minutes"),
             "snippet_html": _snippet(n.body, terms) if terms else html.escape(n.body[:160].replace("\n", " "))}
            for _s, _m, n in results[:limit]]


def tag_counts(user):
    counts = {}
    for note in notes_of(user):
        for tag in note.tags:
            counts.setdefault(tag, []).append({"path": note.path, "name": note.name})
    return sorted(((t, sorted(v, key=lambda x: x["name"].lower())) for t, v in counts.items()), key=lambda x: x[0].lower())


def recent(user, limit=8):
    return [{"path": n.path, "name": n.name, "modified": n.modified.isoformat(timespec="minutes")}
            for n in sorted(notes_of(user), key=lambda n: -n.mtime)[:limit]]


# --------------------------------------------------------------------------- links

def _name_pattern(names):
    names = sorted({n for n in names if len(n) >= 3}, key=len, reverse=True)
    if not names:
        return None
    return re.compile(r"(?<![\w\[])(" + "|".join(re.escape(n) for n in names) + r")(?![\w\]])", re.I)


def mentions(user, rel, notes=None):
    notes = notes_of(user) if notes is None else [n for n in notes if not n.path.startswith(TEMPLATES_PREFIX)]
    resolve = resolver(notes)
    target = next((n for n in notes if n.path == rel), None)
    if target is None:
        return None
    backlinks, unlinked = [], []
    pattern = _name_pattern([target.name, *target.aliases])
    for note in notes:
        if note.path == target.path:
            continue
        if any(resolve(link) is target for link in note.links):
            idx = note.text.find("[[")
            for match in WIKI_RE.finditer(note.text):
                if resolve(link_target(match.group(2))) is target:
                    idx = match.start()
                    break
            backlinks.append({"path": note.path, "name": note.name,
                              "snippet": note.text[max(0, idx - 50): idx + 70].replace("\n", " ").strip()})
            continue
        if pattern is None:
            continue
        plain = "\n".join(WIKI_RE.sub(" ", line) for line in _strip_code(note.body))
        match = pattern.search(plain)
        if match:
            s = max(0, match.start() - 50)
            unlinked.append({"path": note.path, "name": note.name,
                             "snippet_html": html.escape(plain[s:match.start()]) + "<mark>" + html.escape(match.group(0))
                             + "</mark>" + html.escape(plain[match.end():match.end() + 50])})
    return {"path": target.path, "backlinks": backlinks, "unlinked": unlinked}


def graph(user, rel=None, depth=1):
    notes = notes_of(user)
    resolve = resolver(notes)
    edges = set()
    for note in notes:
        for link in note.links:
            other = resolve(link)
            if other is not None and other is not note:
                edges.add((note.path, other.path))
    keep = None
    if rel:
        keep = {rel}
        for _ in range(max(1, depth)):
            keep |= {b for a, b in edges if a in keep} | {a for a, b in edges if b in keep}
    by_path = {n.path: n for n in notes}
    nodes = [{"id": n.path, "name": n.name, "folder": n.folder.split("/")[0] if n.folder else "",
              "tags": n.tags[:3], "current": n.path == rel}
             for n in notes if keep is None or n.path in keep]
    return {"nodes": nodes, "edges": [{"source": a, "target": b} for a, b in sorted(edges)
                                      if (keep is None or (a in keep and b in keep)) and a in by_path and b in by_path]}


def folder_tree(user):
    """Nested folders → notes, for the sidebar tree (folders first, PARA order = name order)."""
    root = {"name": "", "path": "", "folders": {}, "notes": []}
    for note in notes_of(user, include_templates=True):
        node = root
        parts = note.folder.split("/") if note.folder else []
        for i, part in enumerate(parts):
            node = node["folders"].setdefault(part, {"name": part, "path": "/".join(parts[:i + 1]),
                                                      "folders": {}, "notes": []})
        node["notes"].append({"name": note.name, "path": note.path})

    def finish(node):
        return {"name": node["name"], "path": node["path"],
                "folders": [finish(node["folders"][k]) for k in sorted(node["folders"], key=str.lower)],
                "notes": sorted(node["notes"], key=lambda n: n["name"].lower())}
    return finish(root)
