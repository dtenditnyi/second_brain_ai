"""core.git_sync with GitPython replaced by fakes (no network)."""
import os
from unittest import mock

import pytest

from core import git_sync


def test_no_url_returns_false():
    assert git_sync.sync_obsidian_repo("", "tok", "/tmp/x") is False


def test_clone_injects_token_and_creates_parent(tmp_path, monkeypatch):
    repo_cls = mock.Mock()
    monkeypatch.setattr(git_sync, "Repo", repo_cls)
    target = tmp_path / "parent" / "user_1"
    assert git_sync.sync_obsidian_repo("https://github.com/u/v.git", "TOKEN", str(target)) is True
    repo_cls.clone_from.assert_called_once_with("https://TOKEN@github.com/u/v.git", str(target))
    assert (tmp_path / "parent").is_dir()


def test_clone_without_token_uses_plain_url(tmp_path, monkeypatch):
    repo_cls = mock.Mock()
    monkeypatch.setattr(git_sync, "Repo", repo_cls)
    git_sync.sync_obsidian_repo("https://github.com/u/v.git", "", str(tmp_path / "u"))
    assert repo_cls.clone_from.call_args[0][0] == "https://github.com/u/v.git"


def test_incomplete_clone_dir_is_removed_before_clone(tmp_path, monkeypatch):
    target = tmp_path / "user_1"
    target.mkdir()
    (target / "leftover.md").write_text("x")
    seen = {}

    def clone_from(url, path):
        seen["exists_before_clone"] = os.path.exists(path)

    monkeypatch.setattr(git_sync, "Repo", mock.Mock(clone_from=clone_from))
    assert git_sync.sync_obsidian_repo("https://github.com/u/v.git", "t", str(target)) is True
    assert seen["exists_before_clone"] is False


def test_existing_clone_is_pulled(tmp_path, monkeypatch):
    target = tmp_path / "user_1"
    (target / ".git").mkdir(parents=True)
    repo = mock.Mock()
    repo_cls = mock.Mock(return_value=repo)
    monkeypatch.setattr(git_sync, "Repo", repo_cls)
    assert git_sync.sync_obsidian_repo("https://github.com/u/v.git", "T", str(target)) is True
    repo.remotes.origin.set_url.assert_called_once_with("https://T@github.com/u/v.git")
    repo.remotes.origin.pull.assert_called_once()
    repo_cls.clone_from.assert_not_called()


def test_git_error_returns_false_and_does_not_log_token(tmp_path, monkeypatch, caplog):
    def clone_from(url, path):
        raise RuntimeError(f"auth failed for {url}")

    monkeypatch.setattr(git_sync, "Repo", mock.Mock(clone_from=clone_from))
    caplog.set_level("INFO", logger="core.git_sync")
    git_sync.logger.propagate = True
    try:
        assert git_sync.sync_obsidian_repo("https://github.com/u/v.git", "SECRET123", str(tmp_path / "u")) is False
    finally:
        git_sync.logger.propagate = False
    assert "SECRET123" not in caplog.text
