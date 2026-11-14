"""Dataview-lite (Round 5, F2): a small, server-side, read-only subset of Obsidian Dataview.

Supported::

    LIST [expr] | TABLE [WITHOUT ID] f1 [AS "x"], f2 … | TASK
    [FROM "folder" | #tag  (combined with and / or)]
    [WHERE cond]      cond: a and b, a or b, !x, (…), x = / != / < / > / <= / >= value,
                      contains(field, "x"); fields: frontmatter keys, file.name, file.path,
                      file.folder, file.mtime, file.tags, completed / status / text (TASK)
    [SORT field [ASC|DESC]]  [LIMIT n]

Nothing is executed: the query is parsed by this module and evaluated over the in-memory
index of the user's clone (``vault_index``), so it cannot write, cannot reach the network and
cannot leave the vault (``FROM`` paths with ``..``, ``\\``, ``:`` or a leading ``/`` are an error).
DataviewJS / ``dv.*``, ``CALENDAR``, ``GROUP BY``, ``FLATTEN`` and other syntax → ``unsupported``
(the page shows the code with «Откройте в Obsidian»). Evaluation is time-limited.
"""
from __future__ import annotations

import datetime as _dt
import re
import time

from . import vault_index

TIME_LIMIT = 2.0
MAX_ROWS = 500
_TOKEN = re.compile(r'\s*(?:(?P<str>"(?:[^"\\]|\\.)*")|(?P<num>-?\d+(?:\.\d+)?)|(?P<tag>#[\w/-]+)'
                    r'|(?P<op>!=|<=|>=|=|<|>|!|\(|\)|,)|(?P<id>[A-Za-zА-Яа-яЁё_][\w.-]*))', re.U)
_CLAUSES = ("FROM", "WHERE", "SORT", "LIMIT")
_UNSUPPORTED = ("GROUP", "FLATTEN", "CALENDAR")


class Unsupported(Exception):
    pass


class QueryError(Exception):
    pass


class Timeout(Exception):
    pass


def _tokens(text):
    pos, out = 0, []
    text = text.strip()
    while pos < len(text):
        match = _TOKEN.match(text, pos)
        if not match or match.end() == pos:
            raise Unsupported(f"непонятный символ: {text[pos:pos + 10]!r}")
        kind = match.lastgroup
        value = match.group(kind)
        if kind == "str":
            value = value[1:-1].replace('\\"', '"')
        out.append((kind, value))
        pos = match.end()
        while pos < len(text) and text[pos].isspace():
            pos += 1
    return out


class _Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def kw(self, *words):
        kind, value = self.peek()
        return kind == "id" and value.upper() in words

    def take(self):
        tok = self.peek()
        self.i += 1
        return tok

    def expect_op(self, op):
        if self.peek() != ("op", op):
            raise Unsupported(f"ожидалось {op!r}")
        self.i += 1

    # expressions ----------------------------------------------------------
    def expr(self):
        left = self.and_expr()
        while self.kw("OR"):
            self.take()
            left = ("or", left, self.and_expr())
        return left

    def and_expr(self):
        left = self.not_expr()
        while self.kw("AND"):
            self.take()
            left = ("and", left, self.not_expr())
        return left

    def not_expr(self):
        if self.peek() == ("op", "!"):
            self.take()
            return ("not", self.not_expr())
        return self.compare()

    def compare(self):
        left = self.atom()
        kind, value = self.peek()
        if kind == "op" and value in ("=", "!=", "<", ">", "<=", ">="):
            self.take()
            return ("cmp", value, left, self.atom())
        return left

    def atom(self):
        kind, value = self.take()
        if kind == "op" and value == "(":
            inner = self.expr()
            self.expect_op(")")
            return inner
        if kind == "str":
            return ("lit", value)
        if kind == "num":
            return ("lit", float(value))
        if kind == "id":
            low = value.lower()
            if low in ("true", "false"):
                return ("lit", low == "true")
            if low in ("null", "none"):
                return ("lit", None)
            if self.peek() == ("op", "("):
                self.take()
                args = []
                while self.peek() != ("op", ")"):
                    if self.peek()[0] is None:
                        raise Unsupported("незакрытая скобка")
                    args.append(self.expr())
                    if self.peek() == ("op", ","):
                        self.take()
                self.expect_op(")")
                if low not in ("contains", "date", "lower", "length"):
                    raise Unsupported(f"функция {value}() не поддерживается")
                return ("call", low, args)
            return ("field", value)
        raise Unsupported("неожиданный конец запроса" if kind is None else f"неожиданное {value!r}")

    # sources --------------------------------------------------------------
    def source(self):
        left = self.source_atom()
        while self.kw("AND", "OR"):
            op = self.take()[1].lower()
            left = (op, left, self.source_atom())
        return left

    def source_atom(self):
        kind, value = self.take()
        if kind == "str":
            return ("folder", _clean_folder(value))
        if kind == "tag":
            return ("tag", value[1:].lower())
        if kind == "op" and value == "!":
            return ("not", self.source_atom())
        if kind == "op" and value == "(":
            inner = self.source()
            self.expect_op(")")
            return inner
        raise Unsupported("FROM: поддерживаются только \"папка\" и #тег")


def _clean_folder(value):
    value = value.strip()
    if ("\\" in value or ":" in value or value.startswith("/") or ".." in value.split("/")
            or any(part in (".git", ".obsidian", ".trash") for part in value.split("/"))):
        raise QueryError("FROM: путь должен быть папкой внутри хранилища (без .., \\, :).")
    return value.strip("/")


def parse(query):
    text = (query or "").strip()
    first = text.split(None, 1)[0].upper() if text else ""
    if first not in ("LIST", "TABLE", "TASK"):
        raise Unsupported("поддерживаются только LIST, TABLE и TASK")
    tokens = _tokens(text)
    if any(kind == "id" and value.upper() in _UNSUPPORTED for kind, value in tokens):
        raise Unsupported("GROUP BY / FLATTEN / CALENDAR не поддерживаются")
    p = _Parser(tokens)
    q = {"kind": p.take()[1].lower(), "fields": [], "without_id": False,
         "from": None, "where": None, "sort": [], "limit": None}
    if q["kind"] == "table":
        if p.kw("WITHOUT"):
            p.take()
            if not p.kw("ID"):
                raise Unsupported("ожидалось WITHOUT ID")
            p.take()
            q["without_id"] = True
        while p.peek()[0] is not None and not p.kw(*_CLAUSES):
            expr = p.expr()
            label = _label(expr)
            if p.kw("AS"):
                p.take()
                label = p.take()[1]
            q["fields"].append((label, expr))
            if p.peek() == ("op", ","):
                p.take()
    elif q["kind"] == "list" and p.peek()[0] is not None and not p.kw(*_CLAUSES):
        q["fields"].append(("value", p.expr()))
    while p.peek()[0] is not None:
        if p.kw("FROM"):
            p.take()
            q["from"] = p.source()
        elif p.kw("WHERE"):
            p.take()
            q["where"] = p.expr()
        elif p.kw("SORT"):
            p.take()
            while True:
                expr = p.expr()
                direction = "asc"
                if p.kw("ASC", "DESC", "ASCENDING", "DESCENDING"):
                    direction = "desc" if p.take()[1].upper().startswith("DESC") else "asc"
                q["sort"].append((expr, direction))
                if p.peek() != ("op", ","):
                    break
                p.take()
        elif p.kw("LIMIT"):
            p.take()
            kind, value = p.take()
            if kind != "num":
                raise Unsupported("LIMIT: нужно число")
            q["limit"] = max(0, min(int(float(value)), MAX_ROWS))
        else:
            raise Unsupported(f"неожиданное {p.peek()[1]!r}")
    return q


def _label(expr):
    if expr[0] == "field":
        return expr[1]
    return "expr"


# --------------------------------------------------------------------------- evaluation

def _to_value(raw):
    if isinstance(raw, str):
        text = raw.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}([T ]\d{2}:\d{2}(:\d{2})?)?", text):
            try:
                return _dt.datetime.fromisoformat(text.replace(" ", "T")) if len(text) > 10 else _dt.date.fromisoformat(text)
            except ValueError:
                return text
        if re.fullmatch(r"-?\d+(\.\d+)?", text):
            return float(text)
        if text.lower() in ("true", "false"):
            return text.lower() == "true"
    return raw


def _field(name, note, task):
    low = name.lower()
    if low == "file.name":
        return note.name
    if low == "file.path":
        return note.path
    if low == "file.folder":
        return note.folder
    if low in ("file.mtime", "file.mday"):
        return note.modified if low == "file.mtime" else note.modified.date()
    if low == "file.tags":
        return ["#" + t for t in note.tags]
    if low == "file.link":
        return note.name
    if task is not None:
        if low == "completed":
            return task["status"] == "done"
        if low == "status":
            return task["char"]
        if low == "text":
            return task["text"]
    if low == "completed":
        return None
    value = note.meta.get(name, note.meta.get(low))
    if isinstance(value, list):
        return [_to_value(v) for v in value]
    return _to_value(value)


def _comparable(a, b):
    if isinstance(a, _dt.datetime) and isinstance(b, _dt.date) and not isinstance(b, _dt.datetime):
        return a.date(), b
    if isinstance(b, _dt.datetime) and isinstance(a, _dt.date) and not isinstance(a, _dt.datetime):
        return a, b.date()
    if isinstance(a, (int, float)) and isinstance(b, str):
        return str(a), b
    return a, b


def _eval(expr, note, task):
    kind = expr[0]
    if kind == "lit":
        return expr[1]
    if kind == "field":
        return _field(expr[1], note, task)
    if kind == "not":
        return not _truthy(_eval(expr[1], note, task))
    if kind == "and":
        return _truthy(_eval(expr[1], note, task)) and _truthy(_eval(expr[2], note, task))
    if kind == "or":
        return _truthy(_eval(expr[1], note, task)) or _truthy(_eval(expr[2], note, task))
    if kind == "cmp":
        op, a, b = expr[1], _eval(expr[2], note, task), _eval(expr[3], note, task)
        if isinstance(a, list) and op in ("=", "!="):
            hit = b in a or (isinstance(b, str) and b.lstrip("#") in [str(x).lstrip("#") for x in a])
            return hit if op == "=" else not hit
        a, b = _comparable(a, b)
        try:
            return {"=": a == b, "!=": a != b, "<": a < b, ">": a > b, "<=": a <= b, ">=": a >= b}[op]
        except TypeError:
            return False if op != "!=" else True
    if kind == "call":
        name, args = expr[1], [_eval(a, note, task) for a in expr[2]]
        if name == "contains" and len(args) == 2:
            hay, needle = args
            if isinstance(hay, list):
                return any(str(needle).lstrip("#").lower() == str(x).lstrip("#").lower() for x in hay)
            return str(needle).lower() in str(hay or "").lower()
        if name == "date" and len(args) == 1:
            if str(args[0]).lower() == "today" or (expr[2][0][0] == "field" and expr[2][0][1].lower() == "today"):
                return _dt.date.today()
            value = _to_value(str(args[0]))
            return value if isinstance(value, _dt.date) else None
        if name == "lower" and len(args) == 1:
            return str(args[0] or "").lower()
        if name == "length" and len(args) == 1:
            return float(len(args[0] or []))
        raise Unsupported(f"{name}(): неверные аргументы")
    raise Unsupported("выражение не поддерживается")


def _truthy(value):
    return bool(value) and value != "false"


def _in_source(source, note):
    if source is None:
        return True
    kind = source[0]
    if kind == "folder":
        return not source[1] or note.path == source[1] + ".md" or note.path.startswith(source[1] + "/")
    if kind == "tag":
        return any(t.lower() == source[1] or t.lower().startswith(source[1] + "/") for t in note.tags)
    if kind == "not":
        return not _in_source(source[1], note)
    if kind == "and":
        return _in_source(source[1], note) and _in_source(source[2], note)
    return _in_source(source[1], note) or _in_source(source[2], note)


def _display(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "✔" if value else "✘"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, _dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, list):
        return ", ".join(_display(v) for v in value)
    return str(value)


def _sort_key(value):
    if value is None:
        return (0, "")
    if isinstance(value, _dt.datetime):
        return (1, value.isoformat())
    if isinstance(value, _dt.date):
        return (1, value.isoformat())
    if isinstance(value, (int, float)):
        return (2, value)
    return (3, str(value).lower())


def execute(notes, query, deadline=None):
    q = parse(query)
    deadline = deadline or (time.monotonic() + TIME_LIMIT)
    items = []
    for note in notes:
        if time.monotonic() > deadline:
            raise Timeout()
        if not _in_source(q["from"], note):
            continue
        if q["kind"] == "task":
            for task in note.tasks:
                if q["where"] is None or _truthy(_eval(q["where"], note, task)):
                    items.append((note, task))
        elif q["where"] is None or _truthy(_eval(q["where"], note, None)):
            items.append((note, None))
    for expr, direction in reversed(q["sort"]):
        items.sort(key=lambda it: _sort_key(_eval(expr, it[0], it[1])), reverse=direction == "desc")
    if not q["sort"] and q["kind"] != "task":
        items.sort(key=lambda it: it[0].name.lower())
    items = items[: q["limit"] if q["limit"] is not None else MAX_ROWS]
    if q["kind"] == "task":
        rows = [{"path": n.path, "name": n.name, "line": t["line"], "text": t["text"], "status": t["status"],
                 "char": t["char"], "raw": t["raw"]} for n, t in items]
        return {"kind": "task", "columns": [], "rows": rows}
    if q["kind"] == "table":
        columns = ([] if q["without_id"] else ["File"]) + [label for label, _e in q["fields"]]
        rows = [{"path": n.path, "name": n.name,
                 "cells": [_display(_eval(e, n, None)) for _l, e in q["fields"]]} for n, _t in items]
        return {"kind": "table", "columns": columns, "rows": rows}
    rows = [{"path": n.path, "name": n.name,
             "value": _display(_eval(q["fields"][0][1], n, None)) if q["fields"] else ""} for n, _t in items]
    return {"kind": "list", "columns": [], "rows": rows}


def run_on_notes(notes, query):
    try:
        return execute(notes, query)
    except Unsupported as error:
        return {"kind": "unsupported", "message": str(error), "source": query, "rows": []}
    except QueryError as error:
        return {"kind": "error", "message": str(error), "source": query, "rows": []}
    except Timeout:
        return {"kind": "error", "message": "Запрос выполнялся слишком долго.", "source": query, "rows": []}
    except RecursionError:
        return {"kind": "unsupported", "message": "Слишком сложный запрос.", "source": query, "rows": []}


def run(user, query):
    return run_on_notes(vault_index.notes_of(user), query)
