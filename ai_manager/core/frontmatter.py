"""Minimal, byte-preserving frontmatter helpers for the REST API (Link2Note contract).

``parse`` returns string values as written (YAML quotes stripped) and lists (inline
``[a, b]`` or block ``- a``) as arrays. ``set_fields`` changes ONLY the given top-level
keys (a missing key is appended at the end of the frontmatter); everything else stays
byte for byte, including line endings.
"""
import re

_FM = re.compile(r"\A---(\r?\n)(.*?)(\r?\n)---[ \t]*(\r?\n|\Z)", re.S)
_KEY = re.compile(r"^([A-Za-z0-9_][\w.-]*)[ \t]*:(.*)$")


class FrontmatterError(ValueError):
    pass


def _unquote(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


_NEEDS_QUOTES = re.compile(r"^[\s\-?:,\[\]{}#&*!|>'\"%@`]|: |\s#|\s$|^$")


def _quote(text, in_list=False):
    """Double-quote a YAML scalar when plain style would change its meaning (VERIFY M3)."""
    if _NEEDS_QUOTES.search(text) or (in_list and "," in text) or text.lower() in ("true", "false", "null", "~"):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


_LIST_ITEM = re.compile(r"""\s*(?:"(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[^,]+)""")


def _inline_list(value):
    inner = value.strip()[1:-1]
    items = _LIST_ITEM.findall(inner)          # quoted items may hold ","
    return [_unquote(v) for v in items if v.strip()]


def split(text):
    """(frontmatter body, start, end) or None when there is no closed frontmatter."""
    match = _FM.match(text or "")
    if not match:
        return None
    return match.group(2), match.start(2), match.end(2)


def parse(text):
    found = split(text)
    if found is None:
        return None
    body = found[0]
    data, current = {}, None
    for line in body.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        item = re.match(r"^[ \t]*-[ \t]+(.*)$", line)
        if item and current is not None:
            if not isinstance(data[current], list):
                data[current] = []
            data[current].append(_unquote(item.group(1)))
            continue
        match = _KEY.match(line)
        if not match:
            current = None
            continue
        key, value = match.group(1), match.group(2).strip()
        current = key
        if value.startswith("[") and value.endswith("]"):
            data[key] = _inline_list(value)
        elif value == "":
            data[key] = ""            # may become a block list
        else:
            data[key] = _unquote(value)
    return data


def tags_of(meta):
    tags = (meta or {}).get("tags")
    if isinstance(tags, list):
        return [str(t).strip().lstrip("#") for t in tags if str(t).strip()]
    if isinstance(tags, str) and tags.strip():
        return [t.strip().lstrip("#") for t in tags.replace(",", " ").split() if t.strip()]
    return []


def render_value(value, in_list=False):
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(render_value(v, in_list=True) for v in value) + "]"
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        raise FrontmatterError("Значения frontmatter: строки, числа, true/false или списки.")
    if "\n" in value or "\r" in value:
        raise FrontmatterError("Значение frontmatter не может содержать перевод строки.")
    return _quote(value, in_list)


def set_fields(text, values):
    """Return ``text`` with only these top-level keys changed (or appended)."""
    found = split(text)
    if found is None:
        raise FrontmatterError("В заметке нет frontmatter.")
    body, start, end = found
    eol = "\r\n" if "\r\n" in body or text[3:5] == "\r\n" else "\n"
    lines = body.split(eol) if body else []
    for key, value in values.items():
        if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_][\w.-]*", key):
            raise FrontmatterError(f"Недопустимый ключ frontmatter: {key!r}")
        new_line = f"{key}: {render_value(value)}".rstrip() if render_value(value) != "" else f"{key}:"
        index = next((i for i, line in enumerate(lines)
                      if (m := _KEY.match(line)) and m.group(1) == key), None)
        if index is None:
            lines.append(new_line)
            continue
        stop = index + 1                     # a block list under the key belongs to it
        while stop < len(lines) and re.match(r"^[ \t]+-[ \t]|^-[ \t]", lines[stop]):
            stop += 1
        if lines[index:stop] != [new_line]:
            lines[index:stop] = [new_line]
    return text[:start] + eol.join(lines) + text[end:]
