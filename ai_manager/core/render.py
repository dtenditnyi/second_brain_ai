"""Obsidian-like rendering of a note (Round 5, F2) — server side, safe by construction.

* Raw HTML inside notes is NOT passed through (escaped as text); every HTML element this
  module adds comes from placeholders substituted after Markdown, with escaped content.
* Callouts ``> [!type]± title`` (foldable ``-``/``+`` → ``<details>``), clickable task
  checkboxes ``[ ] [x] [/] [>] [-]`` (``data-task-line`` / ``data-task-raw``, toggled through
  ``/api/notes/toggle-task/`` → vault_writer), ``[[Note#Heading|text]]`` links, embeds
  ``![[note]]`` / ``![[note#Heading]]`` (depth-limited) and ``![[img.png]]`` (served by
  ``/attachments/`` with path checks), frontmatter as a properties panel, tables, math
  (``$…$`` / ``$$…$$`` → KaTeX on the client, assets local), ``mermaid`` blocks (local
  Mermaid) and ``dataview`` blocks (Dataview-lite, read-only). Templater ``<% … %>`` is shown
  as text and never executed.
"""
from __future__ import annotations

import html
import re
from pathlib import PurePosixPath
from urllib.parse import quote

import markdown
from markdown.extensions.toc import slugify_unicode

from . import dataview, vault_index
from . import frontmatter as fm_mod

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif"}
MEDIA_EXT = IMAGE_EXT | {".pdf", ".mp3", ".mp4", ".webm", ".ogg", ".wav", ".m4a"}
CALLOUT_ICONS = {
    "note": "✏️", "abstract": "📋", "summary": "📋", "tldr": "📋", "info": "ℹ️", "todo": "☑️",
    "tip": "💡", "hint": "💡", "important": "🔥", "success": "✅", "check": "✅", "done": "✅",
    "question": "❓", "help": "❓", "faq": "❓", "warning": "⚠️", "caution": "⚠️", "attention": "⚠️",
    "failure": "❌", "fail": "❌", "missing": "❌", "danger": "⚡", "error": "⚡", "bug": "🐞",
    "example": "📑", "quote": "❝", "cite": "❝",
}
CALLOUT_ALIAS = {"summary": "abstract", "tldr": "abstract", "hint": "tip", "important": "tip", "check": "success",
                 "done": "success", "help": "question", "faq": "question", "caution": "warning",
                 "attention": "warning", "fail": "failure", "missing": "failure", "error": "danger", "cite": "quote"}
TASK_LABEL = {"todo": "надо", "done": "сделано", "in_progress": "в процессе", "forwarded": "перенесено",
              "cancelled": "отменено"}
MAX_EMBED_DEPTH = 2
_CALLOUT_HEAD = re.compile(r"^\[!([\w-]+)\]([+-]?)\s*(.*)$")
_FENCE = re.compile(r"^(\s*)(```+|~~~+)\s*([\w-]*)")
_TASK = re.compile(r"^(\s*[-*+] )\[(.)\] (.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_INLINE_MATH = re.compile(r"(?<![\\$])\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\d)")
_INLINE_CODE = re.compile(r"(`+)(.+?)\1")


class _Ctx:
    def __init__(self, root, notes, depth, seen):
        self.root, self.notes, self.depth, self.seen = root, notes, depth, seen
        self.resolve = vault_index.resolver(notes)
        self.blocks = {}

    def hold(self, fragment, block=False):
        key = f"SBPH{len(self.blocks)}X{id(self) % 9973}Z"
        self.blocks[key] = fragment
        return f"\n\n{key}\n\n" if block else key


def _attr(value):
    return html.escape(str(value), quote=True)


def attachment_url(name):
    return "/attachments/?name=" + quote(name)


# --------------------------------------------------------------------------- inline pieces

def _wiki(ctx, inner, embed):
    target_raw, _, label = inner.partition("|")
    target = vault_index.link_target(target_raw)
    heading = target_raw.split("#", 1)[1].strip() if "#" in target_raw else ""
    ext = PurePosixPath(target).suffix.lower()
    if embed and ext in MEDIA_EXT:
        url = attachment_url(target)
        if ext in IMAGE_EXT:
            size = f' width="{_attr(label)}"' if label.strip().isdigit() else ""
            alt = label if label and not label.strip().isdigit() else target
            return ctx.hold(f'<img class="note-image" src="{_attr(url)}" alt="{_attr(alt)}" loading="lazy"{size}>')
        return ctx.hold(f'<a class="attachment-link" href="{_attr(url)}" target="_blank" rel="noopener">📎 {html.escape(target)}</a>')
    note = ctx.resolve(target) if target else None
    if embed:
        return ctx.hold(_embed(ctx, note, target, heading), block=True)
    text = label.strip() or (f"{target} › {heading}" if heading and target else heading or target)
    if note is None and target:
        return ctx.hold(f'<a href="#" class="wiki-link unresolved" data-note="{_attr(target)}" '
                        f'title="Заметка не найдена">{html.escape(text)}</a>')
    path = note.path if note else ""
    anchor = f' data-heading="{_attr(slugify_unicode(heading, "-"))}"' if heading else ""
    return ctx.hold(f'<a href="#" class="wiki-link" data-note="{_attr(note.name if note else target)}" '
                    f'data-path="{_attr(path)}"{anchor}>{html.escape(text)}</a>')


def _section(text, heading):
    lines = text.splitlines()
    want = re.sub(r"\W+", "", heading).lower()
    for i, line in enumerate(lines):
        match = _HEADING.match(line)
        if match and re.sub(r"\W+", "", match.group(2)).lower() == want:
            level = len(match.group(1))
            out = [line]
            for nxt in lines[i + 1:]:
                m = _HEADING.match(nxt)
                if m and len(m.group(1)) <= level:
                    break
                out.append(nxt)
            return "\n".join(out)
    return None


def _strip_frontmatter(text):
    found = fm_mod.split(text)
    if not found:
        return text
    nl = text.find("\n", found[2] + 1)
    return text[nl + 1:] if nl >= 0 else ""


def _embed(ctx, note, target, heading):
    title = html.escape(target + (f" › {heading}" if heading else ""))
    if note is None:
        return f'<div class="note-embed unresolved">Встраивание: заметка «{title}» не найдена.</div>'
    if ctx.depth >= MAX_EMBED_DEPTH or note.path in ctx.seen:
        return (f'<div class="note-embed"><a href="#" class="wiki-link" data-note="{_attr(note.name)}" '
                f'data-path="{_attr(note.path)}">{title}</a></div>')
    body = _strip_frontmatter(note.text)
    if heading:
        part = _section(body, heading)
        body = part if part is not None else f"*Раздел «{heading}» не найден.*"
    inner = _render_body(ctx.root, ctx.notes, body, ctx.depth + 1, ctx.seen | {note.path}, note.path)
    return (f'<div class="note-embed" data-path="{_attr(note.path)}"><div class="note-embed-title">'
            f'<a href="#" class="wiki-link" data-note="{_attr(note.name)}" data-path="{_attr(note.path)}">{title}</a>'
            f'</div>{inner}</div>')


def _inline(ctx, line):
    """Placeholders for code spans (kept verbatim), math, wiki links/embeds in one line."""
    parts, last = [], 0
    for match in _INLINE_CODE.finditer(line):
        parts.append(_inline_text(ctx, line[last:match.start()]))
        parts.append(ctx.hold(f"<code>{html.escape(match.group(2))}</code>"))
        last = match.end()
    parts.append(_inline_text(ctx, line[last:]))
    return "".join(parts)


def _inline_text(ctx, text):
    text = vault_index.WIKI_RE.sub(lambda m: _wiki(ctx, m.group(2), bool(m.group(1))), text)
    text = _INLINE_MATH.sub(lambda m: ctx.hold(f'<span class="math math-inline">{html.escape(m.group(1))}</span>'), text)
    return text


# --------------------------------------------------------------------------- blocks

def _dataview_block(ctx, source):
    result = dataview.run_on_notes(ctx.notes, source)
    kind = result["kind"]
    if kind in ("unsupported", "error"):
        note = "Откройте в Obsidian" if kind == "unsupported" else "Ошибка запроса"
        return (f'<div class="dataview dataview-{kind}"><div class="dataview-note">⚠️ {note}: '
                f'{html.escape(result.get("message", ""))}</div><pre><code>{html.escape(source)}</code></pre></div>')
    rows = result["rows"]
    if not rows:
        return '<div class="dataview dataview-empty">Dataview: нет результатов.</div>'

    def link(row):
        return (f'<a href="#" class="wiki-link" data-note="{_attr(row["name"])}" '
                f'data-path="{_attr(row["path"])}">{html.escape(row["name"])}</a>')
    if kind == "list":
        items = "".join(f"<li>{link(r)}{(': ' + html.escape(r['value'])) if r['value'] else ''}</li>" for r in rows)
        return f'<div class="dataview dataview-list"><ul>{items}</ul></div>'
    if kind == "table":
        head = "".join(f"<th>{html.escape(c)}</th>" for c in result["columns"])
        with_id = result["columns"] and result["columns"][0] == "File"
        body = "".join("<tr>" + (f"<td>{link(r)}</td>" if with_id else "")
                       + "".join(f"<td>{html.escape(c)}</td>" for c in r["cells"]) + "</tr>" for r in rows)
        return (f'<div class="dataview dataview-table table-wrap"><table><thead><tr>{head}</tr></thead>'
                f'<tbody>{body}</tbody></table></div>')
    groups = {}
    for row in rows:
        groups.setdefault((row["path"], row["name"]), []).append(row)
    out = []
    for (path, name), items in groups.items():
        lis = "".join(
            f'<li class="task-item task-{r["status"]}"><input type="checkbox" class="task-cb" disabled '
            f'{"checked " if r["status"] == "done" else ""}data-status="{_attr(r["char"])}" '
            f'aria-label="{_attr(TASK_LABEL.get(r["status"], r["status"]))}"> {_inline_simple(r["text"])}</li>'
            for r in items)
        out.append(f'<div class="dataview-task-group">{link({"path": path, "name": name})}<ul class="task-list">{lis}</ul></div>')
    return f'<div class="dataview dataview-task">{"".join(out)}</div>'


def _inline_simple(text):
    return html.escape(vault_index.WIKI_RE.sub(lambda m: (m.group(2).split("|", 1)[-1]), text))


def _callout(ctx, lines, first_line_no):
    head = _CALLOUT_HEAD.match(lines[0])
    kind = head.group(1).lower()
    fold = head.group(2)
    css = CALLOUT_ALIAS.get(kind, kind if kind in CALLOUT_ICONS else "note")
    title = head.group(3).strip() or kind.capitalize()
    inner = _render_body(ctx.root, ctx.notes, "\n".join(lines[1:]), ctx.depth, ctx.seen, None, line_offset=None)
    title_html = _md_inline(ctx, title)
    icon = CALLOUT_ICONS.get(kind, "✏️")
    if fold:
        return (f'<details class="callout callout-{css}" data-callout="{_attr(kind)}"{" open" if fold == "+" else ""}>'
                f'<summary class="callout-title"><span aria-hidden="true">{icon}</span> {title_html}</summary>'
                f'<div class="callout-content">{inner}</div></details>')
    return (f'<div class="callout callout-{css}" data-callout="{_attr(kind)}"><div class="callout-title">'
            f'<span aria-hidden="true">{icon}</span> {title_html}</div><div class="callout-content">{inner}</div></div>')


def _md_inline(ctx, text):
    rendered = _markdown(_inline(ctx, text))
    rendered = re.sub(r"^<p>|</p>$", "", rendered.strip())
    return _restore(ctx, rendered)


def _properties(meta):
    if not meta:
        return ""
    rows = []
    for key, value in meta.items():
        if isinstance(value, list):
            shown = "".join(f'<span class="badge">{html.escape(str(v))}</span>' for v in value) or "—"
        else:
            shown = html.escape(str(value)) or "—"
        rows.append(f"<dt>{html.escape(key)}</dt><dd>{shown}</dd>")
    return (f'<details class="note-properties" open><summary>Свойства</summary>'
            f'<dl>{"".join(rows)}</dl></details>')


def _markdown(text):
    md = markdown.Markdown(extensions=["fenced_code", "tables", "sane_lists", "toc"],
                           extension_configs={"toc": {"slugify": slugify_unicode, "permalink": False}})
    md.preprocessors.deregister("html_block")
    md.inlinePatterns.deregister("html")
    return md.convert(text)


def _restore(ctx, rendered):
    for _ in range(4):
        changed = False
        for key, fragment in ctx.blocks.items():
            if key in rendered:
                rendered = rendered.replace(f"<p>{key}</p>", fragment).replace(key, fragment)
                changed = True
        if not changed:
            break
    return rendered


def _render_body(root, notes, body, depth, seen, rel, line_offset=0):
    ctx = _Ctx(root, notes, depth, seen)
    lines = body.split("\n")
    out, i = [], 0
    while i < len(lines):
        line = lines[i]
        fence = _FENCE.match(line)
        if fence:
            marker, lang = fence.group(2), fence.group(3).lower()
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith(marker[:3]):
                j += 1
            code = "\n".join(lines[i + 1:j])
            if lang == "dataview":
                out.append(ctx.hold(_dataview_block(ctx, code), block=True))
            elif lang == "mermaid":
                out.append(ctx.hold(f'<pre class="mermaid">{html.escape(code)}</pre>', block=True))
            elif lang in ("math", "latex"):
                out.append(ctx.hold(f'<div class="math math-display">{html.escape(code)}</div>', block=True))
            else:
                note = ('<div class="code-note">Код DataviewJS / Templater не выполняется — откройте в Obsidian.</div>'
                        if lang in ("dataviewjs", "templater") else "")
                cls = f' class="language-{_attr(lang)}"' if lang else ""
                out.append(ctx.hold(f"{note}<pre><code{cls}>{html.escape(code)}</code></pre>", block=True))
            i = j + 1
            continue
        if line.strip().startswith("$$"):
            j = i
            chunk = line.strip()[2:]
            if chunk.endswith("$$") and len(chunk) >= 2:
                math, j = chunk[:-2], i
            else:
                collected = [chunk]
                j = i + 1
                while j < len(lines) and "$$" not in lines[j]:
                    collected.append(lines[j])
                    j += 1
                if j < len(lines):
                    collected.append(lines[j].split("$$", 1)[0])
                math = "\n".join(collected)
            out.append(ctx.hold(f'<div class="math math-display">{html.escape(math.strip())}</div>', block=True))
            i = j + 1
            continue
        stripped = line.lstrip()
        if stripped.startswith(">") and _CALLOUT_HEAD.match(stripped[1:].strip()):
            block, j = [], i
            while j < len(lines) and lines[j].lstrip().startswith(">"):
                content = lines[j].lstrip()[1:]
                block.append(content[1:] if content.startswith(" ") else content)
                j += 1
            out.append(ctx.hold(_callout(ctx, [block[0].strip()] + block[1:], i), block=True))
            i = j
            continue
        task = _TASK.match(line)
        if task:
            char = task.group(2)
            status = vault_index.TASK_STATUS.get(char, "todo")
            attrs = (f'data-task-raw="{_attr(line)}" data-status="{_attr(char)}"'
                     + (f' data-task-line="{i + line_offset}"' if line_offset is not None and rel else ' data-task-line="" disabled'))
            box = ctx.hold(f'<input type="checkbox" class="task-cb task-{status}" {attrs} '
                           f'{"checked " if char in "xX" else ""}aria-label="{_attr(TASK_LABEL.get(status, status))}">')
            out.append(f"{task.group(1)}{box} {_inline(ctx, task.group(3))}")
            i += 1
            continue
        out.append(_inline(ctx, line))
        i += 1
    rendered = _markdown("\n".join(out))
    rendered = re.sub(r"<li>(\s*(?:<p>)?\s*)(SBPH\d+X\d+Z)", lambda m: '<li class="task-item">' + m.group(1) + m.group(2)
                      if '"task-cb' in ctx.blocks.get(m.group(2), "") else m.group(0), rendered)
    return _restore(ctx, rendered)


def render_note(root, rel, text, notes=None):
    """{"html": properties panel + body}; ``notes`` = vault_index notes of this vault."""
    notes = notes if notes is not None else vault_index.scan_root(root)
    meta = fm_mod.parse(text) or {}
    body = _strip_frontmatter(text)
    offset = text[: len(text) - len(body)].count("\n") if body != text else 0
    return {"html": _properties(meta) + _render_body(root, notes, body, 0, {rel}, rel, line_offset=offset),
            "meta": meta}
