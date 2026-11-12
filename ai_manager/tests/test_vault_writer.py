"""Unit tests for core.vault_writer with real local git repositories (no network)."""
import os
import subprocess
from pathlib import Path

import git
import pytest

from core import vault_writer as vw
from tests import vault_helpers as vh


@pytest.fixture
def real_git(monkeypatch):
    from core import git_sync
    monkeypatch.setattr(git_sync, "Repo", git.Repo)
    monkeypatch.setattr(vw, "Repo", git.Repo)


@pytest.mark.parametrize("ok", ["a.md", "Папка/Заметка 🚀.md", "01 - Projects/🎯 Цели и планы/Задачи.md", "a/./b.md"])
def test_safe_path_accepts_normal_paths(tmp_path, ok):
    path = vw.safe_path(tmp_path, ok)
    assert path.is_relative_to(tmp_path.resolve())


@pytest.mark.parametrize("bad", [None, 5, "a\x00b.md", "\\\\server\\share\\x.md", ".", "sub/.git/hooks/x", ".trash/x.md"])
def test_safe_path_rejects_more(tmp_path, bad):
    with pytest.raises(vw.UnsafePath):
        vw.safe_path(tmp_path, bad)


def test_unsafe_path_is_a_vault_error():
    err = vw.UnsafePath("nope")
    assert isinstance(err, vw.VaultError) and err.kind == "unsafe" and str(err) == "nope"


@pytest.mark.parametrize("message,kind", [
    ("! [rejected] HEAD -> main (fetch first)", "conflict"),
    ("error: failed to push some refs", "conflict"),
    ("remote: Permission to u/v.git denied to bot. fatal: ... 403", "permission"),
    ("fatal: Authentication failed for 'https://github.com/u/v.git/'", "permission"),
    ("fatal: could not read Username for 'https://github.com'", "permission"),
    ("fatal: unable to access 'https://github.com/': Could not resolve host: github.com", "offline"),
    ("ssh: connect to host github.com port 22: Connection timed out", "offline"),
    ("fatal: something else entirely", "git"),
])
def test_classify_git_error(message, kind):
    assert vw.classify_git_error(message) == kind


def test_lock_timeout_and_release(tmp_path):
    target = tmp_path / "vault"
    with vw.vault_lock(target):
        with pytest.raises(vw.VaultError) as err:
            with vw.vault_lock(target, timeout=0.1):
                pass
        assert err.value.kind == "locked"
    with vw.vault_lock(target, timeout=0.1):     # released afterwards
        pass


def test_repo_clone_pull_commit_push_cycle(tmp_path, real_git):
    remote = vh.make_remote(tmp_path, files={"a.md": "one\n"})
    repo = vw.VaultRepo(tmp_path / "clone", str(remote))
    repo.pull()
    (tmp_path / "clone" / "a.md").write_bytes(b"two\n")  # byte-exact: autocrlf=false since B-49
    assert repo.commit(["a.md"], "edit") is True
    assert repo.commit(["a.md"], "nothing new") is False
    repo.push()
    assert vh.remote_file(remote, "a.md", tmp_path) == "two\n"
    assert vh.remote_log(remote)[0] == ["Second Brain", "edit"]
    assert len(repo.head()) == 40


def test_pull_resets_local_junk_and_recovers_broken_clone(tmp_path, real_git):
    remote = vh.make_remote(tmp_path, files={"a.md": "one\n"})
    clone = tmp_path / "clone"
    repo = vw.VaultRepo(clone, str(remote))
    repo.pull()
    (clone / "a.md").write_text("local edit\n", encoding="utf-8")
    (clone / "junk.md").write_text("x", encoding="utf-8")
    repo.pull()
    assert (clone / "a.md").read_text(encoding="utf-8") == "one\n" and not (clone / "junk.md").exists()
    # a folder without .git (interrupted clone) is replaced by a fresh clone
    vw.remove_tree(clone / ".git")
    repo.pull()
    assert (clone / ".git").exists()


def test_pull_with_dirty_clone_and_remote_ahead(tmp_path, real_git):
    """B-71: local edits (e.g. CRLF copies from an old autocrlf=true checkout) to files that
    changed on the remote must not abort the pull with "would be overwritten by checkout"."""
    remote = vh.make_remote(tmp_path, files={"a.md": "one\n", "b.md": "b\n"})
    clone = tmp_path / "clone"
    repo = vw.VaultRepo(clone, str(remote))
    repo.pull()
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, "a.md", "two\n")
    (clone / "a.md").write_bytes(b"one\r\n")          # CRLF copy of the old version
    (clone / "b.md").write_bytes(b"b\r\n")
    repo.pull()
    assert (clone / "a.md").read_bytes() == b"two\n" and (clone / "b.md").read_bytes() == b"b\n"
    assert vh.git(clone, "status", "--porcelain").stdout.strip() == ""


def test_push_to_empty_remote(tmp_path, real_git):
    remote = tmp_path / "empty.git"
    vh.git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    repo = vw.VaultRepo(tmp_path / "clone", str(remote))
    repo.pull()
    (tmp_path / "clone" / "n.md").write_bytes(b"first\n")
    assert repo.commit(["n.md"], "first commit")
    repo.push()
    assert vh.remote_file(remote, "n.md", tmp_path) == "first\n"


def test_git_failures_become_vault_errors(tmp_path, real_git):
    repo = vw.VaultRepo(tmp_path / "clone", str(tmp_path / "does-not-exist.git"))
    with pytest.raises(vw.VaultError) as err:
        repo.pull()
    assert err.value.kind in ("git", "offline")


def test_vault_apply_rejects_operation_returning_unsafe_path(db, user, tmp_path, real_git, isolated_vault):
    remote = vh.make_remote(tmp_path, files={"a.md": "x\n"})
    s = user.settings
    s.github_repo_url = str(remote)
    s.save()
    with pytest.raises(vw.UnsafePath):
        vw.vault_apply(user, lambda root: ([".git/config"], None), "bad")


def test_vault_apply_without_repo_is_an_error(db, user):
    with pytest.raises(vw.VaultError) as err:
        vw.vault_apply(user, lambda root: ([], None), "x")
    assert "Настройках" in str(err.value)


def test_vault_apply_no_change_means_no_commit(db, user, tmp_path, real_git, isolated_vault):
    remote = vh.make_remote(tmp_path, files={"a.md": "x\n"})
    s = user.settings
    s.github_repo_url = str(remote)
    s.save()
    before = vh.remote_log(remote)
    assert vw.vault_apply(user, lambda root: ([], "nothing"), "x") == "nothing"
    # writing identical content is not a commit either
    assert vw.vault_apply(user, lambda root: (["a.md"], "same"), "x") == "same"
    assert vh.remote_log(remote) == before


def test_vault_apply_gives_up_after_retries(db, user, tmp_path, real_git, isolated_vault, monkeypatch):
    remote = vh.make_remote(tmp_path, files={"a.md": "x\n"})
    s = user.settings
    s.github_repo_url = str(remote)
    s.save()
    calls = []

    def always_conflict(self):
        calls.append(1)
        raise vw.VaultError("conflict", "rejected")

    monkeypatch.setattr(vw.VaultRepo, "push", always_conflict)

    def op(root):
        (Path(root) / "a.md").write_text(f"y{len(calls)}\n", encoding="utf-8")
        return ["a.md"], None

    with pytest.raises(vw.VaultError) as err:
        vw.vault_apply(user, op, "x", retries=2)
    assert err.value.kind == "conflict" and len(calls) == 3
