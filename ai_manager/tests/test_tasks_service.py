"""Unit tests for core.tasks_service (note ↔ cache, outbox, legacy mode) and its views."""
from unittest import mock

import git
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from core import tasks_service as ts
from core import vault_writer as vw
from core.models import Task, UserSettings, VaultOutbox
from tests import vault_helpers as vh

pytestmark = pytest.mark.django_db


@pytest.fixture
def real_git(monkeypatch):
    from core import git_sync
    monkeypatch.setattr(git_sync, "Repo", git.Repo)
    monkeypatch.setattr(vw, "Repo", git.Repo)


@pytest.fixture
def no_raise_client(user):
    from django.test import Client
    client = Client(raise_request_exception=False)
    client.force_login(user)
    return client


@pytest.fixture
def remote(tmp_path):
    return vh.make_remote(tmp_path)


@pytest.fixture
def vuser(user, remote, real_git, isolated_vault):
    s = user.settings
    s.github_repo_url = str(remote)
    s.save()
    return user


# --- legacy (no vault) ---------------------------------------------------------

def test_legacy_mode_keeps_database_tasks(user):
    assert ts.sync_tasks(user) == {"status": "local"}
    task = ts.add_task(user, "plain", priority="high", tags="work, x", due="2026-01-01")
    assert task.tags == "work, x" and task.synced
    ts.update_task(user, task.pk, title="plain 2", tags="a,b", status="done")
    task.refresh_from_db()
    assert (task.title, task.tags, task.status) == ("plain 2", "a, b", "done")
    ts.delete_task(user, task.pk)
    assert not Task.objects.filter(pk=task.pk).exists()


def test_tasks_note_path_strips_and_defaults(user, settings):
    user.settings.tasks_note_path = "   "
    user.settings.save()
    assert ts.tasks_note_path(user) == settings.TASKS_NOTE_PATH


# --- vault mode ------------------------------------------------------------------

def test_first_sync_keeps_old_database_only_tasks(vuser):
    """Connecting a vault must not delete tasks that were never exported."""
    Task.objects.create(user=vuser, title="Old DB task")
    ts.sync_tasks(vuser, force=True)
    assert Task.objects.filter(user=vuser, title="Old DB task").exists()


def test_legacy_row_in_vault_mode_is_edited_locally(vuser, remote, tmp_path):
    old = Task.objects.create(user=vuser, title="Old DB task")
    ts.update_task(vuser, old.pk, title="renamed")
    old.refresh_from_db()
    assert old.title == "renamed" and "renamed" not in vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    ts.delete_task(vuser, old.pk)
    assert not Task.objects.filter(pk=old.pk).exists()


def test_note_is_created_when_missing(user, tmp_path, real_git, isolated_vault):
    remote = vh.make_remote(tmp_path, files={"README.md": "hi\n"}, name="empty-ish.git")
    s = user.settings
    s.github_repo_url = str(remote)
    s.save()
    assert ts.sync_tasks(user, force=True)["note_exists"] is False
    ts.add_task(user, "first", tags=["planning"])
    note = vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)
    assert note.startswith("---\ntags: [planning]\ntype: tasks-db") and "- [ ] first #planning" in note


def test_add_with_unknown_tag_is_rejected_before_writing(vuser, remote, tmp_path):
    before = vh.remote_log(remote)
    with pytest.raises(ValueError):
        ts.add_task(vuser, "x", tags="work")
    assert vh.remote_log(remote) == before and not Task.objects.filter(title="x").exists()


def test_update_without_real_change_does_not_commit(vuser, remote):
    ts.sync_tasks(vuser, force=True)
    task = Task.objects.get(user=vuser, vault_id="t7k2m9")
    before = vh.remote_log(remote)
    ts.update_task(vuser, task.pk, title=task.title, priority=task.priority, tags=task.tags,
                   due_date=task.due_date, status=task.status, unknown_field="ignored")
    assert vh.remote_log(remote) == before


def test_editing_a_line_without_id_assigns_one(vuser, remote, tmp_path):
    ts.sync_tasks(vuser, force=True)
    task = Task.objects.get(user=vuser, title="Задача без ID")
    assert task.vault_id == ""
    ts.update_task(vuser, task.pk, status="done")
    task.refresh_from_db()
    assert task.vault_id and f"- [x] Задача без ID #planning ✅" in vh.remote_file(remote, vh.TASKS_NOTE, tmp_path)


def test_delete_task_already_deleted_elsewhere_is_quiet(vuser, remote, tmp_path):
    ts.sync_tasks(vuser, force=True)
    task = Task.objects.get(user=vuser, vault_id="t7k2m9")
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, vh.TASKS_NOTE, vh.FIXTURE_VAULT[vh.TASKS_NOTE].replace("🆔 t7k2m9", "🆔 other1"))
    ts.delete_task(vuser, task.pk)
    assert not Task.objects.filter(pk=task.pk).exists()


def test_sync_reports_git_errors_without_raising(vuser, monkeypatch):
    monkeypatch.setattr(vw.VaultRepo, "pull", lambda self: (_ for _ in ()).throw(vw.VaultError("git", "boom")))
    result = ts.sync_tasks(vuser, force=True)
    assert result["status"] == "error" and "boom" in result["error"]
    vuser.settings.refresh_from_db()
    assert vuser.settings.tasks_sync_error == "boom"


def test_sync_with_pending_outbox_stays_offline(vuser, monkeypatch):
    ts.sync_tasks(vuser, force=True)
    offline = lambda self: (_ for _ in ()).throw(vw.VaultError("offline", "no network"))  # noqa: E731
    monkeypatch.setattr(vw.VaultRepo, "pull", offline)
    ts.add_task(vuser, "queued")
    assert ts.sync_tasks(vuser, force=True)["status"] == "offline"
    assert VaultOutbox.objects.filter(user=vuser).count() == 1
    assert str(VaultOutbox.objects.first()).startswith(f"{vuser.username}: tasks add")


def test_generic_git_failure_on_write_is_a_sync_error(vuser, monkeypatch):
    ts.sync_tasks(vuser, force=True)
    monkeypatch.setattr(vw.VaultRepo, "push", lambda self: (_ for _ in ()).throw(vw.VaultError("git", "weird")))
    with pytest.raises(ts.TaskSyncError, match="weird"):
        ts.add_task(vuser, "x")
    assert not Task.objects.filter(user=vuser, title="x").exists()


def test_export_reports_dropped_tags_and_needs_vault(vuser, user_without_vault=None):
    Task.objects.create(user=vuser, title="Legacy", tags="work, dev", status="in_progress", priority="medium")
    preview, count, dropped = ts.export_preview(vuser)
    assert count == 1 and dropped == ["work"] and "- [/] Legacy 🔼 #dev" in preview


def test_export_command_errors(user, other_user):
    with pytest.raises(CommandError, match="not found"):
        call_command("export_tasks_to_note", "--user", "nobody")
    with pytest.raises(CommandError, match="no GitHub vault"):
        call_command("export_tasks_to_note", "--user", user.username)


def test_sync_command_single_user_and_unknown(vuser, capsys):
    call_command("sync_tasks", "--user", vuser.username)
    assert "ok" in capsys.readouterr().out
    with pytest.raises(CommandError):
        call_command("sync_tasks", "--user", "nobody")


def test_sync_command_reports_failures(vuser, monkeypatch, capsys):
    monkeypatch.setattr(vw.VaultRepo, "pull", lambda self: (_ for _ in ()).throw(vw.VaultError("offline", "down")))
    call_command("sync_tasks", "--all")
    captured = capsys.readouterr()
    assert "offline" in captured.err and "synced 0/1" in captured.out


# --- views -------------------------------------------------------------------------

def test_tasks_page_survives_unexpected_sync_crash(auth_client, user, monkeypatch):
    s = user.settings
    s.github_repo_url = "https://github.com/u/v.git"
    s.save()
    monkeypatch.setattr(ts, "sync_tasks", mock.Mock(side_effect=RuntimeError("bug")))
    assert auth_client.get("/tasks/").status_code == 200
    assert auth_client.get("/").status_code == 200


def test_tasks_page_shows_local_mode_hint(auth_client):
    html = auth_client.get("/tasks/").content.decode()
    assert "Tasks are stored on this site" in html and 'id="tasks-refresh"' not in html


@pytest.mark.parametrize("path,ok", [("02 - Areas/Мои задачи.md", True), ("../x.md", False), (".obsidian/x.md", False),
                                     ("notes/tasks.txt", False), ("x" * 301, False), ("", True)])
def test_settings_tasks_note_path_validation(no_raise_client, user, post_json, path, ok):
    r = post_json(no_raise_client, "/api/save-settings/", {"tasks_note_path": path})
    assert (r.status_code == 200) is ok, r.content
    if ok:
        assert UserSettings.objects.get(user=user).tasks_note_path == path


def test_task_api_errors(no_raise_client, user, post_json):
    t = Task.objects.create(user=user, title="a")
    assert post_json(no_raise_client, "/api/delete-task/", {"task_id": "x"}).status_code == 400
    assert post_json(no_raise_client, "/api/delete-task/", {"task_id": 999}).status_code == 404
    assert no_raise_client.get("/api/delete-task/").status_code == 400
    assert no_raise_client.get("/api/tasks/sync/").status_code == 400
    assert post_json(no_raise_client, "/api/delete-task/", raw="{").status_code == 400
    assert post_json(no_raise_client, "/api/update-task/", {"task_id": t.pk}).status_code == 400
    assert post_json(no_raise_client, "/api/update-task/", {"task_id": t.pk, "title": "  "}).status_code == 400
    assert post_json(no_raise_client, "/api/update-task/", {"task_id": t.pk, "due_date": "soon"}).status_code == 400
    assert post_json(no_raise_client, "/api/tasks/sync/", {}).json() == {"status": "local"}


def test_task_api_sync_error_is_409_with_message(auth_client, vuser, post_json, monkeypatch):
    ts.sync_tasks(vuser, force=True)
    monkeypatch.setattr(vw.VaultRepo, "push", lambda self: (_ for _ in ()).throw(vw.VaultError("permission", "403")))
    r = post_json(auth_client, "/api/add-task/", {"title": "x"})
    assert r.status_code == 409 and "Contents: Read and write" in r.json()["msg"]
    t = Task.objects.get(user=vuser, vault_id="t7k2m9")
    assert post_json(auth_client, "/api/update-task/", {"task_id": t.pk, "status": "done"}).status_code == 409
    assert post_json(auth_client, "/api/delete-task/", {"task_id": t.pk}).status_code == 409
    assert post_json(auth_client, "/api/add-task/", {"title": "y", "tags": "work"}).status_code == 400


def test_sync_endpoint_503_when_offline(auth_client, vuser, monkeypatch):
    monkeypatch.setattr(vw.VaultRepo, "pull", lambda self: (_ for _ in ()).throw(vw.VaultError("offline", "down")))
    r = auth_client.post("/api/tasks/sync/")
    assert r.status_code == 503 and r.json()["status"] == "offline"


def test_export_command_reports_dropped_tags_and_vault_errors(vuser, capsys, monkeypatch):
    Task.objects.create(user=vuser, title="Legacy", tags="work, dev")
    call_command("export_tasks_to_note", "--user", vuser.username)
    out = capsys.readouterr().out
    assert "exported 1 task(s)" in out and "dropped: work" in out
    monkeypatch.setattr(vw.VaultRepo, "pull", lambda self: (_ for _ in ()).throw(vw.VaultError("offline", "down")))
    with pytest.raises(CommandError, match="down"):
        call_command("export_tasks_to_note", "--user", vuser.username, "--dry-run")
