"""core.git_sync with GitPython replaced by fakes, plus real local git repos
(no network: remotes point to unreachable URLs and pull/clone are stubbed)."""
import base64
import os
from unittest import mock

import git
import pytest

from core import git_sync

TOKEN = "ghp_SECRET_TOKEN_123"
URL = "https://github.com/u/v.git"


def test_no_url_returns_false():
    assert git_sync.sync_obsidian_repo("", "tok", "/tmp/x") is False


def test_auth_env_puts_token_only_in_http_header():
    env = git_sync.auth_env(TOKEN, URL)
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraHeader"  # scoped to the repo host
    basic = env["GIT_CONFIG_VALUE_0"].split("Basic ")[1]
    assert base64.b64decode(basic).decode() == f"x-access-token:{TOKEN}"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_auth_env_without_token_or_for_non_https():
    assert "GIT_CONFIG_COUNT" not in git_sync.auth_env("", URL)
    assert "GIT_CONFIG_COUNT" not in git_sync.auth_env(TOKEN, "git@github.com:u/v.git")


def test_clone_uses_plain_url_and_token_via_env(tmp_path, monkeypatch):
    repo_cls = mock.Mock()
    monkeypatch.setattr(git_sync, "Repo", repo_cls)
    target = tmp_path / "parent" / "user_1"
    assert git_sync.sync_obsidian_repo(URL, TOKEN, str(target)) is True
    args, kwargs = repo_cls.clone_from.call_args
    assert args == (URL, str(target))
    assert TOKEN not in args[0]
    assert "GIT_CONFIG_VALUE_0" in kwargs["env"]
    assert (tmp_path / "parent").is_dir()


def test_clone_without_token_uses_plain_url(tmp_path, monkeypatch):
    repo_cls = mock.Mock()
    monkeypatch.setattr(git_sync, "Repo", repo_cls)
    git_sync.sync_obsidian_repo(URL, "", str(tmp_path / "u"))
    assert repo_cls.clone_from.call_args[0][0] == URL
    assert "GIT_CONFIG_COUNT" not in repo_cls.clone_from.call_args[1]["env"]


def test_incomplete_clone_dir_is_removed_before_clone(tmp_path, monkeypatch):
    target = tmp_path / "user_1"
    target.mkdir()
    (target / "leftover.md").write_text("x")
    seen = {}

    def clone_from(url, path, env=None):
        seen["exists_before_clone"] = os.path.exists(path)

    monkeypatch.setattr(git_sync, "Repo", mock.Mock(clone_from=clone_from))
    assert git_sync.sync_obsidian_repo(URL, "t", str(target)) is True
    assert seen["exists_before_clone"] is False


def test_existing_clone_is_pulled_with_plain_url(tmp_path, monkeypatch):
    target = tmp_path / "user_1"
    (target / ".git").mkdir(parents=True)
    repo = mock.MagicMock()
    repo_cls = mock.Mock(return_value=repo)
    monkeypatch.setattr(git_sync, "Repo", repo_cls)
    assert git_sync.sync_obsidian_repo(URL, "T", str(target)) is True
    for call in repo.remotes.origin.set_url.call_args_list:
        assert call.args == (URL,)
    repo.git.custom_environment.assert_called_once()
    assert "GIT_CONFIG_VALUE_0" in repo.git.custom_environment.call_args.kwargs
    repo.remotes.origin.pull.assert_called_once()
    repo_cls.clone_from.assert_not_called()


def test_git_error_returns_false_and_does_not_log_token(tmp_path, monkeypatch, caplog):
    def clone_from(url, path, env=None):
        raise RuntimeError(f"auth failed for {url} {env}")

    monkeypatch.setattr(git_sync, "Repo", mock.Mock(clone_from=clone_from))
    caplog.set_level("INFO", logger="core.git_sync")
    git_sync.logger.propagate = True
    try:
        assert git_sync.sync_obsidian_repo(URL, "SECRET123", str(tmp_path / "u")) is False
    finally:
        git_sync.logger.propagate = False
    assert "SECRET123" not in caplog.text


# --- real git repositories: the token never lands in .git/config (Q13) -------

def _config_text(path):
    with open(os.path.join(path, ".git", "config"), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture
def real_git(monkeypatch):
    monkeypatch.setattr(git_sync, "Repo", git.Repo)


def _legacy_clone(path):
    """A vault cloned by the OLD code: the token is embedded in the origin URL."""
    repo = git.Repo.init(path)
    repo.create_remote("origin", f"https://{TOKEN}@github.com/u/v.git")
    return repo


@pytest.mark.parametrize("pull_fails", [False, True])
def test_pull_leaves_no_token_in_git_config(tmp_path, real_git, monkeypatch, pull_fails):
    target = tmp_path / "user_1"
    _legacy_clone(target)
    assert TOKEN in _config_text(target)
    seen = {}

    def fake_pull(self, *a, **k):
        seen["config_during_pull"] = _config_text(target)
        if pull_fails:
            raise git.GitCommandError("pull", 128, "fatal: Authentication failed")
        return []

    monkeypatch.setattr(git.Remote, "pull", fake_pull)
    assert git_sync.sync_obsidian_repo(URL, TOKEN, str(target)) is (not pull_fails)
    assert TOKEN not in seen["config_during_pull"]
    assert TOKEN not in _config_text(target)
    assert "url = https://github.com/u/v.git" in _config_text(target)


def test_failure_after_tokenised_url_is_cleaned_in_finally(tmp_path, real_git, monkeypatch):
    """Even if set_url itself blew up mid-way, the finally block restores the plain URL."""
    target = tmp_path / "user_1"
    _legacy_clone(target)
    calls = {"n": 0}
    real_set_url = git.Remote.set_url

    def flaky_set_url(self, url, *a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise git.GitCommandError("remote", 1, "locked")
        return real_set_url(self, url, *a, **k)

    monkeypatch.setattr(git.Remote, "set_url", flaky_set_url)
    assert git_sync.sync_obsidian_repo(URL, TOKEN, str(target)) is False
    assert TOKEN not in _config_text(target)


@pytest.mark.parametrize("clone_fails", [False, True])
def test_clone_leaves_no_token_in_git_config(tmp_path, real_git, monkeypatch, clone_fails):
    target = tmp_path / "user_1"
    seen = {}

    def fake_clone_from(url, to_path, env=None, **kwargs):
        # What git itself does: create the repo and store the given URL as origin.
        seen["url"], seen["env"] = url, env
        repo = git.Repo.init(to_path)
        repo.create_remote("origin", url)
        if clone_fails:
            raise git.GitCommandError("clone", 128, "fatal: could not read from remote")
        return repo

    monkeypatch.setattr(git.Repo, "clone_from", staticmethod(fake_clone_from))
    assert git_sync.sync_obsidian_repo(URL, TOKEN, str(target)) is (not clone_fails)
    assert TOKEN not in seen["url"] and seen["env"]["GIT_CONFIG_COUNT"] == "1"
    assert TOKEN not in _config_text(target)


def test_real_git_accepts_env_header_config(tmp_path):
    """git really reads http.extraHeader from GIT_CONFIG_* (needs git >= 2.31)."""
    repo = git.Repo.init(tmp_path / "r")
    env = git_sync.auth_env(TOKEN, URL)
    with repo.git.custom_environment(**env):
        value = repo.git.config("--get-urlmatch", "http.extraHeader", URL)
        other = repo.git.config("--get-urlmatch", "http.extraHeader", "https://evil.example/x.git", with_exceptions=False)
    assert value.startswith("Authorization: Basic ")
    assert other == ""  # not sent to other hosts
    assert TOKEN not in _config_text(tmp_path / "r")
