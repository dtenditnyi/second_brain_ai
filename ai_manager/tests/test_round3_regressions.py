"""Regression tests for the findings of the Round 3 verification (docs/audit/round3/VERIFY-1.md)."""
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath
from unittest import mock

import git
import pytest

from core import tasks_md, tasks_service as ts, vault_writer as vw
from core.models import Task
from tests import vault_helpers as vh

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "ai_manager"


@pytest.fixture
def real_git(monkeypatch):
    from core import git_sync
    monkeypatch.setattr(git_sync, "Repo", git.Repo)
    monkeypatch.setattr(vw, "Repo", git.Repo)


@pytest.fixture
def remote(tmp_path):
    return vh.make_remote(tmp_path)


@pytest.fixture
def vuser(db, user, remote, real_git, isolated_vault):
    s = user.settings
    s.github_repo_url = str(remote)
    s.save()
    return user


# --- B-34 duplicate IDs ------------------------------------------------------------

def test_b34_duplicate_id_does_not_hide_a_task_or_edit_the_wrong_line(vuser, remote, tmp_path):
    ts.sync_tasks(vuser, force=True)
    phone = vh.clone(remote, tmp_path / "phone")
    note = vh.FIXTURE_VAULT[vh.TASKS_NOTE].replace("- [ ] Задача без ID #planning", "- [ ] Дубликат 🆔 t7k2m9")
    vh.commit_and_push(phone, vh.TASKS_NOTE, note)
    ts.sync_tasks(vuser, force=True)
    ts.sync_tasks(vuser, force=True)
    titles = set(Task.objects.filter(user=vuser).values_list("title", flat=True))
    assert {"Сдать лабу по физике", "Дубликат"} <= titles
    ids = list(Task.objects.filter(user=vuser).exclude(vault_id="").values_list("vault_id", flat=True))
    assert len(ids) == len(set(ids))
    dup = Task.objects.get(user=vuser, title="Дубликат")
    ts.update_task(vuser, dup.pk, status="done")
    text = vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    assert "- [x] Дубликат" in text and "- [ ] Сдать лабу по физике" in text


def test_b34_duplicates_are_kept_apart_even_when_the_fix_cannot_be_pushed(vuser, monkeypatch):
    text = "## 📥 Входящие\n- [ ] A 🆔 same11\n- [ ] B 🆔 same11\n"
    monkeypatch.setattr(ts, "_read_note", lambda user: text)
    monkeypatch.setattr(ts, "_write", lambda user, ops: None)       # offline
    for _ in range(2):                                              # the 2nd sync used to collapse them (VERIFY-2 R4)
        ts.sync_tasks(vuser, force=True)
        rows = list(Task.objects.filter(user=vuser).values_list("title", "vault_id", "vault_line"))
        assert {r[0] for r in rows} == {"A", "B"} and len(rows) == 2
    assert [r[1] for r in rows if r[0] == "A"] == ["same11"] and [r[1] for r in rows if r[0] == "B"] == [""]


# --- B-35 tags ------------------------------------------------------------------------

def test_b35_task_with_tag_from_obsidian_stays_editable(vuser, remote, tmp_path):
    phone = vh.clone(remote, tmp_path / "phone")
    note = vh.FIXTURE_VAULT[vh.TASKS_NOTE].replace("## ✅ Выполнено\n", "## ✅ Выполнено\n- [ ] X #work 🆔 wk0001\n")
    vh.commit_and_push(phone, vh.TASKS_NOTE, note)
    ts.sync_tasks(vuser, force=True)
    task = Task.objects.get(user=vuser, vault_id="wk0001")
    ts.update_task(vuser, task.pk, title="X2", tags=task.tags, priority=task.priority, status="in_progress")
    assert "- [/] X2 #work 🆔 wk0001" in vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    ts.update_task(vuser, task.pk, tags="work, dev")       # adding an allowed tag next to it
    with pytest.raises(ValueError):
        ts.update_task(vuser, task.pk, tags="work, games-night")


def test_b35_heading_links_are_not_tags():
    task = tasks_md.parse("- [ ] read [[Note#Heading]] and [[#Local]] [[N|#alias]] #dev\n").tasks[0]
    assert task.tags == ["dev"]


def test_b35_apply_op_allows_existing_unlisted_tags():
    out, _ = tasks_md.apply_op("- [ ] X #work 🆔 a1a1a1\n", {"op": "update", "id": "a1a1a1", "tags": ["work", "dev"]})
    assert out == "- [ ] X #work #dev 🆔 a1a1a1\n"


# --- B-36 safe_path -----------------------------------------------------------------------

@pytest.mark.parametrize("bad", [".GIT/config", ".git./config", ".obsidian./x.md", ".Obsidian/workspace.json",
                                 "notes/.Git/x.md", "CON", "con.md", "notes/NUL.txt", "LPT1.md", "x.md::$DATA",
                                 "x.md.", "dir /x.md", "x\tmd", "a:b.md"])
def test_b36_windows_tricks_rejected(tmp_path, bad):
    with pytest.raises(vw.UnsafePath):
        vw.safe_path(tmp_path, bad)


def test_m1_dotdot_layer_rejects_on_its_own(tmp_path):
    """The '..' check must reject by itself (not only via the resolve check)."""
    (tmp_path / "a" / "b").mkdir(parents=True)
    with pytest.raises(vw.UnsafePath, match=r"\.\."):
        vw.safe_path(tmp_path, "a/b/../x.md")     # would resolve INSIDE the vault


def test_b36_tasks_note_path_cannot_point_into_git(no_raise_client, post_json):
    r = post_json(no_raise_client, "/api/save-settings/", {"tasks_note_path": ".GIT/x.md"})
    assert r.status_code == 400


@pytest.fixture
def no_raise_client(user):
    from django.test import Client
    client = Client(raise_request_exception=False)
    client.force_login(user)
    return client


# --- B-41 parser edge cases ---------------------------------------------------------------

def test_b41_delete_parent_removes_its_subtasks():
    src = "## In\n- [ ] parent 🆔 pppppp\n    - [ ] child\n    notes\n- [ ] next 🆔 nnnnnn\n"
    out, _ = tasks_md.apply_op(src, {"op": "delete", "id": "pppppp"})
    assert out == "## In\n- [ ] next 🆔 nnnnnn\n"


def test_b41_longer_fence_with_inner_fence():
    src = "````md\n```\n- [ ] inside\n```\n````\n- [ ] outside\n"
    assert [t.text for t in tasks_md.parse(src).tasks] == ["outside"]
    assert tasks_md.serialize(tasks_md.parse(src)) == src


def test_b41_frontmatter_comment_is_not_a_section():
    src = "---\n# comment\ntags: [planning]\n---\n- [ ] t\n"
    assert tasks_md.parse(src).tasks[0].section is None


def test_b41_protected_branch_is_permission_not_conflict():
    msg = "remote: error: GH006: Protected branch update failed for refs/heads/main.\n ! [remote rejected] main -> main (protected branch hook declined)"
    assert vw.classify_git_error(msg) == "permission"


# --- B-37 / B-42 image ------------------------------------------------------------------------

def _dockerignored(rel):
    """Approximation of Docker's .dockerignore matching (last matching rule wins)."""
    excluded = False
    for raw in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        pattern = line.lstrip("!").rstrip("/")
        path = PurePosixPath(rel)
        candidates = [path, *path.parents][:-1]
        if any(c.full_match(pattern) for c in candidates):
            excluded = not negate
    return excluded


@pytest.mark.parametrize("rel", ["ai_manager/db.sqlite3", "ai_manager/audit_copy_db.sqlite3", "ai_manager/.coverage",
                                 "ai_manager/core/__pycache__/x.pyc", "ai_manager/node_modules/x/y.js", ".env",
                                 "ai_manager/obsidian_data/user_1/a.md", "ai_manager/chroma_db/x.bin",
                                 "ai_manager/logs/system.log", "ai_manager/tests/test_x.py", "venv/x",
                                 "ai_manager/cloudflared.exe", "docs/audit/round3/responsive/a.png"])
def test_b37_sensitive_files_are_excluded_from_the_build_context(rel):
    assert _dockerignored(rel), rel


@pytest.mark.parametrize("rel", ["ai_manager/manage.py", "ai_manager/core/models.py", "requirements.txt",
                                 ".env.example", "docker/entrypoint.sh", "ai_manager/static/css/input.css"])
def test_b37_needed_files_are_in_the_build_context(rel):
    assert not _dockerignored(rel), rel


def test_b42_code_is_not_writable_by_the_app_user():
    final = (ROOT / "Dockerfile").read_text(encoding="utf-8").split("AS runtime")[1]
    assert "COPY --chown=app" not in final and "chown -R app:app /app\n" not in final
    assert "chown -R app:app /data ai_manager/logs" in final


# --- B-38 scheduler ---------------------------------------------------------------------

def test_b38_task_sync_does_not_import_torch():
    code = ("import django, sys; django.setup(); "
            "from core.management.commands import sync_tasks; from core import tasks_service, vault_writer; "
            "print('torch' in sys.modules, 'llama_index.core' in sys.modules, 'core.rag_engine' in sys.modules)")
    env = {**os.environ, "DJANGO_SETTINGS_MODULE": "ai_manager.settings_test"}
    out = subprocess.run([sys.executable, "-c", code], cwd=APP, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "False False False"


def test_b38_sync_loop_keeps_one_process(db, user, monkeypatch, capsys):
    from django.core.management import call_command
    calls = []
    monkeypatch.setattr("time.sleep", lambda s: calls.append(s))
    call_command("sync_tasks", "--all", "--loop", "5", "--max-iterations", "3")
    assert calls == [5, 5] and capsys.readouterr().out.count("synced") == 3


def test_b38_loop_survives_a_failing_round(db, monkeypatch, capsys):
    from django.core.management import call_command
    from core.management.commands import sync_tasks as cmd
    monkeypatch.setattr("time.sleep", lambda s: None)
    monkeypatch.setattr(cmd.Command, "_once", mock.Mock(side_effect=RuntimeError("boom")))
    call_command("sync_tasks", "--loop", "1", "--max-iterations", "2")
    assert capsys.readouterr().err.count("boom") == 2


# --- B-33 / B-39 deploy scripts ------------------------------------------------------------

def test_b33_restore_recreates_schema_in_one_transaction():
    text = (ROOT / "deploy" / "restore.sh").read_text(encoding="utf-8")
    assert "DROP SCHEMA IF EXISTS public CASCADE" in text and "CREATE SCHEMA public" in text
    assert "--single-transaction" in text and "ON_ERROR_STOP=1" in text
    assert text.index("DROP SCHEMA") < text.index('gunzip -c "$dump"')


def test_b39_update_remembers_deployed_commit_and_resets_on_error():
    text = (ROOT / "deploy" / "update.sh").read_text(encoding="utf-8")
    assert ".deployed_commit" in text and "trap " in text and 'git reset --hard "$previous"' in text
    assert "git rev-parse HEAD > \"$state_file\"" in text
    assert ".deployed_commit" in (ROOT / "deploy" / "install.sh").read_text(encoding="utf-8")


# --- M8 healthz -----------------------------------------------------------------------------

def test_m8_healthz_requires_the_query_to_succeed(client, db):
    with mock.patch("core.views.health.connection") as conn:
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.execute.side_effect = Exception("relation does not exist")
        r = client.get("/healthz/")
    assert r.status_code == 503
    with mock.patch("core.views.health.connection") as conn:
        r = client.get("/healthz/")
        assert conn.cursor.return_value.__enter__.return_value.execute.call_args[0][0] == "SELECT 1"


# --- VERIFY-2 follow-up (B-44 … B-48, mutation gaps N3 / N13) -------------------------

def test_b44_read_only_token_with_duplicate_ids_still_shows_tasks(vuser, monkeypatch):
    text = "## 📥 Входящие\n- [ ] A 🆔 same11\n- [ ] B 🆔 same11\n"
    monkeypatch.setattr(ts, "_read_note", lambda user: text)

    def denied(user, ops):
        raise ts.TaskSyncError(vw.PERMISSION_HINT)

    monkeypatch.setattr(ts, "_write", denied)
    result = ts.sync_tasks(vuser, force=True)
    assert result["status"] == "ok"
    assert set(Task.objects.filter(user=vuser).values_list("title", flat=True)) == {"A", "B"}
    vuser.settings.refresh_from_db()
    assert "Contents: Read and write" in vuser.settings.tasks_sync_error


def test_n3_sync_repairs_duplicate_ids_in_the_note(vuser, remote, tmp_path):
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, vh.TASKS_NOTE, vh.FIXTURE_VAULT[vh.TASKS_NOTE].replace(
        "- [ ] Задача без ID #planning", "- [ ] Копия 🆔 t7k2m9"))
    ts.sync_tasks(vuser, force=True)
    ids = [t.id for t in tasks_md.parse(vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)).tasks if t.id]
    assert len(ids) == len(set(ids)) and ids.count("t7k2m9") == 1


@pytest.mark.parametrize("text", ["---\n## In\n- [ ] a 🆔 aaaaaa\n", "---\n- [ ] top task\n"])
def test_b45_unclosed_leading_dashes_are_not_frontmatter(text):
    note = tasks_md.parse(text)
    assert len(note.tasks) == 1
    out, _ = tasks_md.apply_op(text, {"op": "add", "text": "new"})
    assert len(tasks_md.parse(out).tasks) == 2


def test_b46_update_script_fires_err_trap_inside_functions():
    text = (ROOT / "deploy" / "update.sh").read_text(encoding="utf-8")
    assert "set -Eeuo pipefail" in text


def test_b48_delete_parent_with_blank_line_inside_subitems():
    src = "- [ ] p 🆔 pppppp\n\tnote\n\n    - [ ] child\n- [ ] n 🆔 nnnnnn\n"
    out, _ = tasks_md.apply_op(src, {"op": "delete", "id": "pppppp"})
    assert out == "- [ ] n 🆔 nnnnnn\n"
    keep = "- [ ] p 🆔 pppppp\n\n- [ ] n 🆔 nnnnnn\n"
    assert tasks_md.apply_op(keep, {"op": "delete", "id": "pppppp"})[0] == "\n- [ ] n 🆔 nnnnnn\n"


def test_n13_link_to_git_folder_inside_vault_is_rejected(tmp_path):
    vault = tmp_path / "vault"
    (vault / ".git").mkdir(parents=True)
    link = vault / "innocent"
    try:
        os.symlink(vault / ".git", link, target_is_directory=True)
    except (OSError, NotImplementedError):
        if os.name != "nt":
            pytest.skip("symlinks not permitted")
        r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(vault / ".git")], capture_output=True)
        if r.returncode != 0:
            pytest.skip("cannot create a junction")
    with pytest.raises(vw.UnsafePath):
        vw.safe_path(vault, "innocent/config")
