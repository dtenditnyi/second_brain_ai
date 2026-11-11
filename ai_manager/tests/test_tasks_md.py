"""Unit tests for core.tasks_md (pure module, no Django)."""
import datetime

import pytest

from core import tasks_md as t

TODAY = datetime.date(2026, 11, 11)


def test_module_does_not_import_django():
    import ast
    import inspect
    tree = ast.parse(inspect.getsource(t))
    names = [n.names[0].name if isinstance(n, ast.Import) else (n.module or "") for n in ast.walk(tree)
             if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not [n for n in names if n.startswith("django")]


@pytest.mark.parametrize("text", ["", "\n", "no tasks here", "- [ ]", "- [ ] ", "* [x] star bullet\n", "1. [/] numbered",
                                  "- [?] unknown mark", "﻿- [ ] with BOM", "- [ ] trailing\r", "```\n- [ ] in code\n```"])
def test_roundtrip_edge_inputs(text):
    assert t.serialize(t.parse(text)) == text


def test_tasks_in_fenced_code_are_ignored():
    note = t.parse("```dataview\n- [ ] not a task\n```\n~~~\n- [x] no\n~~~\n- [ ] real\n")
    assert [x.text for x in note.tasks] == ["real"]


def test_statuses_priorities_and_fields():
    text = ("- [ ] a 🔺\n- [/] b ⏫\n- [x] c 🔼 ✅ 2026-01-02\n- [-] d 🔽 ❌ 2026-01-03\n- [>] e ⏬\n- [?] f\n"
            "- [ ] g 📅 2026-02-03 🛫 2026-02-01 🔁 every week #dev #ai 🆔 abc123\n")
    by = {x.text: x for x in t.parse(text).tasks}
    assert [by[k].status for k in "abcdef"] == ["todo", "in_progress", "done", "cancelled", "forwarded", "todo"]
    assert [by[k].priority for k in "abcde"] == ["urgent", "high", "medium", "low", "low"]
    assert by["c"].done == "2026-01-02" and by["d"].cancelled_on == "2026-01-03"
    g = by["g"]
    assert (g.due, g.tags, g.id) == ("2026-02-03", ["dev", "ai"], "abc123")
    assert "🛫 2026-02-01" in g.extra and "🔁 every week" in g.extra


def test_inline_tags_and_html_entity_hash_not_a_tag():
    task = t.parse("- [ ] Read #books chapter &#35;5 issue#7 #2026\n").tasks[0]
    assert task.tags == ["books"] and task.text.startswith("Read #books")


def test_render_keeps_original_priority_emoji_and_unknown_fields():
    src = "- [ ] Отчёт ⏬ ⏳ 2026-11-12 🆔 q1w2e3\n"
    out, _ = t.apply_op(src, {"op": "update", "id": "q1w2e3", "text": "Отчёт 2"})
    assert out == "- [ ] Отчёт 2 ⏬ ⏳ 2026-11-12 🆔 q1w2e3\n"


def test_add_validation_errors():
    with pytest.raises(ValueError):
        t.apply_op("", {"op": "add", "text": "   "})
    with pytest.raises(ValueError):
        t.apply_op("", {"op": "add", "text": "x 📅 2026-01-01"})
    with pytest.raises(ValueError):
        t.apply_op("", {"op": "add", "text": "x" * 501})
    with pytest.raises(ValueError):
        t.apply_op("", {"op": "add", "text": "x", "priority": "galactic"})
    with pytest.raises(ValueError):
        t.apply_op("", {"op": "add", "text": "x", "due": "31.12.2026"})
    with pytest.raises(ValueError):
        t.apply_op("", {"op": "add", "text": "x", "status": "maybe"})
    with pytest.raises(ValueError):
        t.apply_op("", {"op": "explode"})


def test_add_multiline_text_is_flattened_and_tags_normalised():
    out, info = t.apply_op("", {"op": "add", "text": "line1\nline2", "tags": ["#dev", "dev", " ai "]}, today=TODAY)
    assert "- [ ] line1 line2 #dev #ai ➕ 2026-11-11 🆔 " in out


def test_add_replayed_operation_is_not_duplicated():
    out, info = t.apply_op("", {"op": "add", "text": "x", "id": "fixed1"}, today=TODAY)
    again, info2 = t.apply_op(out, {"op": "add", "text": "x", "id": "fixed1"}, today=TODAY)
    assert again == out and info2["duplicate"]


def test_add_into_existing_custom_section_and_missing_section():
    src = "## 🔥 Срочно\n- [ ] a 🆔 aaaaaa\n\n## Other\ntext\n🔗 [[Главная (Home)]]\n"
    out, _ = t.apply_op(src, {"op": "add", "text": "b", "section": "🔥 Срочно"}, today=TODAY)
    assert out.index("- [ ] b") < out.index("## Other")
    out2, _ = t.apply_op(src, {"op": "add", "text": "c"}, today=TODAY)
    assert out2.index("## 📥 Входящие") < out2.index("- [ ] c") < out2.index("🔗 [[Главная (Home)]]")
    assert out2.rstrip().endswith("🔗 [[Главная (Home)]]")


def test_add_to_note_without_trailing_newline_and_crlf():
    out, _ = t.apply_op("intro", {"op": "add", "text": "x"}, today=TODAY)
    assert out.startswith("intro\n\n## 📥 Входящие\n- [ ] x")
    out2, _ = t.apply_op("intro\r\n## 📥 Входящие\r\n", {"op": "add", "text": "y"}, today=TODAY)
    assert "\n" not in out2.replace("\r\n", "") and out2.endswith("🆔 " + t.parse(out2).tasks[0].id + "\r\n")


def test_add_after_subtasks_of_last_task():
    src = "## 📥 Входящие\n- [ ] parent\n    - [ ] child\n    notes line\n\n## Next\n"
    out, _ = t.apply_op(src, {"op": "add", "text": "new"}, today=TODAY)
    lines = out.splitlines()
    assert lines.index("    notes line") + 1 == [i for i, l in enumerate(lines) if "new" in l][0]


def test_update_status_transitions_dates():
    src = "- [ ] a 🆔 aaaaaa\n"
    done, _ = t.apply_op(src, {"op": "update", "id": "aaaaaa", "status": "done"}, today=TODAY)
    assert "- [x] a ✅ 2026-11-11 🆔 aaaaaa" in done
    back, _ = t.apply_op(done, {"op": "update", "id": "aaaaaa", "status": "todo"}, today=TODAY)
    assert back == "- [ ] a 🆔 aaaaaa\n"
    cancelled, _ = t.apply_op(src, {"op": "update", "id": "aaaaaa", "status": "cancelled"}, today=TODAY)
    assert "- [-] a ❌ 2026-11-11 🆔 aaaaaa" in cancelled


def test_update_clear_due_priority_and_tags():
    src = "- [ ] a 📅 2026-01-01 ⏫ #dev #ai 🆔 aaaaaa\n"
    out, _ = t.apply_op(src, {"op": "update", "id": "aaaaaa", "due": None, "priority": None, "tags": ["ai"]})
    assert out == "- [ ] a #ai 🆔 aaaaaa\n"


def test_update_removes_inline_tag_that_was_dropped():
    out, _ = t.apply_op("- [ ] buy #books now 🆔 aaaaaa\n", {"op": "update", "id": "aaaaaa", "tags": []})
    assert out == "- [ ] buy now 🆔 aaaaaa\n"


def test_update_by_line_assigns_id_and_delete_by_line():
    src = "- [ ] no id here\n"
    out, info = t.apply_op(src, {"op": "update", "line": "- [ ] no id here", "status": "in_progress"})
    assert info["id"] and out == f"- [/] no id here 🆔 {info['id']}\n"
    gone, _ = t.apply_op(src, {"op": "delete", "line": "- [ ] no id here"})
    assert gone == ""


def test_missing_task_raises_not_found():
    with pytest.raises(t.TaskNotFound):
        t.apply_op("- [ ] a 🆔 aaaaaa\n", {"op": "update", "id": "zzzzzz", "status": "done"})
    with pytest.raises(t.TaskNotFound):
        t.apply_op("- [ ] a\n", {"op": "delete", "line": "- [ ] b"})
    with pytest.raises(t.TaskNotFound):
        t.parse("").by_id("x")


def test_validate_tags_rejects_unknown_and_skips_blank():
    assert t.validate_tags(["", " ", "#dev"]) == ["dev"]
    with pytest.raises(ValueError, match="не разрешён"):
        t.validate_tags(["work"])


def test_generate_id_is_unique_against_existing():
    ids = {t.generate_id([]) for _ in range(200)}
    assert all(len(i) == 6 and i.isalnum() and i == i.lower() for i in ids)


def test_new_note_crlf_variant():
    text = t.new_tasks_note(TODAY, eol="\r\n")
    assert text.count("\r\n") == text.count("\n")
    assert t.serialize(t.parse(text)) == text


def test_render_without_text_and_subtask_indent():
    task = t.parse("  - [ ] 📅 2026-01-01\n").tasks[0]
    assert task.text == "" and task.is_subtask and t.render(task) == "  - [ ] 📅 2026-01-01"
