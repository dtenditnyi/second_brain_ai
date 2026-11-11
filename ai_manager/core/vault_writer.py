"""The single way the site writes to a user's Obsidian vault (Round 3 / G-C3).

Every writer (tasks, later the note editor, the AI agent and the REST API) calls
``vault_apply(user, operation, message)``:

    lock (per vault, shared by all gunicorn workers on this host and by git_sync)
      → fetch + hard reset to the remote branch (the local clone is only a cache)
      → operation(vault_root) → list of changed paths (+ a result)
      → commit as "Second Brain" → push
      → push rejected (someone pushed meanwhile)? fetch again and re-run the SAME
        operation on the new state, up to VAULT_PUSH_RETRIES times.

Because the operation is re-applied (not the file re-written), concurrent edits
from Obsidian, the phone or another worker are never lost. Paths are validated
with ``safe_path``: only files inside the vault, never ``.git/`` or ``.obsidian/``.
The token travels only in the git process environment (see git_sync.auth_env).
"""
from __future__ import annotations

import os
import re
import time
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from git import GitCommandError, Repo

from .git_sync import auth_env

AUTHOR_NAME = "Second Brain"
AUTHOR_EMAIL = "second-brain@localhost"
FORBIDDEN_PARTS = {".git", ".obsidian", ".trash"}
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
_RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

PERMISSION_HINT = ("GitHub отклонил запись: у токена нет права записи в репозиторий хранилища. "
                   "Создайте fine-grained PAT с доступом «Contents: Read and write» и сохраните его в Настройках.")


class VaultError(Exception):
    """kind: offline | permission | conflict | locked | unsafe | git"""

    def __init__(self, kind, message=""):
        super().__init__(message or kind)
        self.kind = kind
        self.message = message or kind

    def __str__(self):
        return self.message


class UnsafePath(VaultError):
    def __init__(self, message):
        super().__init__("unsafe", message)


def safe_path(root, rel) -> Path:
    """Absolute path of ``rel`` inside ``root``; raises UnsafePath for anything else."""
    if not isinstance(rel, str) or not rel.strip() or "\x00" in rel:
        raise UnsafePath("Пустой или недопустимый путь.")
    if rel.endswith(("/", "\\")):
        raise UnsafePath("Путь указывает на папку, а не на файл.")
    if rel.startswith(("/", "\\")) or _DRIVE_RE.match(rel) or os.path.isabs(rel):
        raise UnsafePath("Абсолютные пути запрещены.")
    raw_parts = rel.replace("\\", "/").split("/")
    if ".." in raw_parts:
        raise UnsafePath("Переход вверх по папкам («..») запрещён.")
    if ":" in rel or any(ord(ch) < 32 for ch in rel):
        raise UnsafePath("Недопустимые символы в пути (':' или управляющие символы).")
    parts = PurePosixPath(rel.replace("\\", "/")).parts
    for part in parts:
        # Windows ignores trailing dots/spaces and letter case: ".GIT." is ".git" (B-36).
        if part != part.rstrip(" .") and part not in (".",):
            raise UnsafePath("Имена файлов и папок не могут заканчиваться точкой или пробелом.")
        if part.casefold() in FORBIDDEN_PARTS:
            raise UnsafePath("Служебные папки (.git, .obsidian) изменять нельзя.")
        if part.split(".")[0].upper() in _RESERVED_NAMES:
            raise UnsafePath("Зарезервированное имя Windows (CON, NUL, COM1…) недопустимо.")
    root_resolved = Path(root).resolve()
    target = (root_resolved / Path(*parts)).resolve()
    try:
        inside = target.relative_to(root_resolved)
    except ValueError:
        raise UnsafePath("Путь ведёт за пределы хранилища (символическая ссылка?).") from None
    if target == root_resolved:
        raise UnsafePath("Путь указывает на корень хранилища.")
    if any(part.casefold().rstrip(" .") in FORBIDDEN_PARTS for part in inside.parts):
        raise UnsafePath("Служебные папки (.git, .obsidian) изменять нельзя.")
    return target


def remove_tree(path):
    """shutil.rmtree that also removes read-only files (git objects on Windows)."""
    import shutil
    import stat

    def make_writable(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onexc=make_writable)


# --------------------------------------------------------------------------- lock

class _FileLock:
    """Exclusive inter-process lock on ``<vault>.lock`` (works across gunicorn workers)."""

    def __init__(self, path, timeout):
        self.path, self.timeout, self.handle = Path(str(path) + ".lock"), timeout, None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = open(self.path, "a+b")
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._lock()
                return self
            except OSError:
                if time.monotonic() >= deadline:
                    self.handle.close()
                    self.handle = None
                    raise VaultError("locked", "Хранилище сейчас занято другой операцией, попробуйте ещё раз.")
                time.sleep(0.05)

    def _lock(self):
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def __exit__(self, *exc):
        try:
            self.handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None
        return False


def vault_lock(local_dir, timeout=120):
    """Context manager holding the vault's lock (also used by git_sync for pulls)."""
    return _FileLock(local_dir, timeout)


# --------------------------------------------------------------------------- git

def classify_git_error(error) -> str:
    text = str(error).lower()
    if any(s in text for s in ("[rejected]", "fetch first", "non-fast-forward", "failed to push some refs",
                               "updates were rejected", "cannot lock ref", "stale info")):
        return "conflict"
    if any(s in text for s in ("protected branch", "gh006", "pre-receive hook declined")):
        return "permission"   # retrying cannot help (B-41)
    if any(s in text for s in ("403", "permission to", "permission denied", "authentication failed",
                               "write access", "access denied", "could not read username", "invalid username",
                               "the requested url returned error: 401")):
        return "permission"
    if any(s in text for s in ("could not resolve host", "unable to access", "failed to connect", "connection",
                               "timed out", "network is unreachable", "temporary failure", "could not read from remote")):
        return "offline"
    return "git"


def _pin_autocrlf(repo):
    """Set core.autocrlf=false (and core.longpaths=true, B-51) in this clone only;
    True when autocrlf was changed (the checkout must then be renormalised)."""
    with repo.config_reader() as reader:
        current = str(reader.get_value("core", "autocrlf", "")).lower()
        longpaths = str(reader.get_value("core", "longpaths", "")).lower()
    if longpaths != "true":            # Git for Windows: note names up to 120 chars in deep folders
        with repo.config_writer() as writer:
            writer.set_value("core", "longpaths", "true")
    if current == "false":
        return False
    with repo.config_writer() as writer:
        writer.set_value("core", "autocrlf", "false")
    return True


class VaultRepo:
    """One user's local clone (a cache of the remote vault)."""

    def __init__(self, local_dir, repo_url, token=""):
        self.local_dir = Path(local_dir)
        self.repo_url = repo_url
        self.env = auth_env(token, repo_url)
        self.env.update({
            "GIT_AUTHOR_NAME": AUTHOR_NAME, "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
            "GIT_COMMITTER_NAME": AUTHOR_NAME, "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL,
        })
        self.branch = None

    def _git(self, *args):
        repo = Repo(self.local_dir)
        with repo.git.custom_environment(**self.env):
            return repo.git.execute(["git", *args])

    def _run(self, fn):
        try:
            return fn()
        except GitCommandError as error:
            kind = classify_git_error(f"{error.stderr} {error.stdout} {error}")
            raise VaultError(kind, PERMISSION_HINT if kind == "permission" else
                             ("Нет связи с GitHub — изменение сохранено в очередь и будет отправлено позже."
                              if kind == "offline" else f"Ошибка git: {(error.stderr or str(error)).strip()[:300]}")) from error

    def pull(self):
        """Make the clone identical to the remote branch (clone it when missing)."""
        def run():
            if not (self.local_dir / ".git").exists():
                if self.local_dir.exists() and any(self.local_dir.iterdir()):
                    remove_tree(self.local_dir)     # interrupted clone: start over
                self.local_dir.parent.mkdir(parents=True, exist_ok=True)
                Repo.clone_from(self.repo_url, self.local_dir, env=self.env)
            repo = Repo(self.local_dir)
            repo.remotes.origin.set_url(self.repo_url)
            # Notes must stay byte-exact (Git for Windows defaults to autocrlf=true,
            # which would hand the editor CRLF text and break hashes/diffs — B-49).
            renormalize = _pin_autocrlf(repo)
            self._git("fetch", "--prune", "origin")
            remote_branches = [ref.remote_head for ref in repo.remotes.origin.refs if ref.remote_head != "HEAD"]
            if not remote_branches:          # empty remote: nothing to reset to
                self.branch = self.branch or "main"
                return
            try:
                current = repo.active_branch.name
            except TypeError:
                current = None
            self.branch = current if current in remote_branches else (
                "main" if "main" in remote_branches else remote_branches[0])
            self._git("checkout", "-B", self.branch, f"origin/{self.branch}")
            if renormalize:                  # drop CRLF copies checked out earlier
                self._git("rm", "-r", "--cached", "--quiet", "--ignore-unmatch", ".")
            self._git("reset", "--hard", f"origin/{self.branch}")
            self._git("clean", "-fd")
        self._run(run)

    def commit(self, paths, message) -> bool:
        def run():
            self._git("add", "--all", "--", *paths)
            if not self._git("status", "--porcelain", "--", *paths).strip():
                return False
            self._git("commit", "-m", message, "--", *paths)
            return True
        return self._run(run)

    def push(self):
        self._run(lambda: self._git("push", "origin", f"HEAD:refs/heads/{self.branch or 'main'}"))

    def head(self):
        return self._run(lambda: self._git("rev-parse", "HEAD"))


def _user_repo(user):
    from .models import get_user_settings
    from .paths import get_user_paths
    settings = get_user_settings(user)
    if not settings.github_repo_url:
        raise VaultError("git", "Хранилище не подключено: укажите репозиторий GitHub в Настройках.")
    return VaultRepo(get_user_paths(user)["notes_dir"], settings.github_repo_url, settings.github_token)


def vault_read(user, reader):
    """Fresh read-only access: lock → pull → reader(root)."""
    repo = _user_repo(user)
    with vault_lock(repo.local_dir):
        repo.pull()
        return reader(repo.local_dir)


def vault_apply(user, operation, message, retries=None, with_commit=False):
    """Apply ``operation(root) -> (changed_rel_paths, result)`` and push it; returns ``result``
    (or ``(result, commit_sha)`` with ``with_commit=True``; sha is None when nothing changed).

    Raises VaultError(kind=offline|permission|conflict|locked|git).
    """
    from django.conf import settings as dj_settings
    retries = getattr(dj_settings, "VAULT_PUSH_RETRIES", 4) if retries is None else retries
    repo = _user_repo(user)
    done = (lambda result, sha=None: (result, sha)) if with_commit else (lambda result, sha=None: result)
    with vault_lock(repo.local_dir):
        for attempt in range(retries + 1):
            repo.pull()
            changed, result = operation(repo.local_dir)
            if not changed:
                return done(result)
            for rel in changed:
                safe_path(repo.local_dir, rel)
            if not repo.commit(list(changed), message):
                return done(result)
            try:
                repo.push()
                return done(result, repo.head().strip())
            except VaultError as error:
                if error.kind != "conflict" or attempt == retries:
                    raise
        raise VaultError("conflict", "Не удалось отправить изменения: хранилище слишком часто меняется, попробуйте ещё раз.")


def vault_revert(user, sha, retries=None):
    """Revert one commit of the site (e.g. an applied AI batch) with a revert commit and push it.

    Raises VaultError("conflict") when later edits touch the same lines (nothing is pushed then).
    """
    from django.conf import settings as dj_settings
    if not re.fullmatch(r"[0-9a-f]{7,40}", str(sha or "")):
        raise VaultError("git", "Некорректный идентификатор коммита.")
    retries = getattr(dj_settings, "VAULT_PUSH_RETRIES", 4) if retries is None else retries
    repo = _user_repo(user)
    with vault_lock(repo.local_dir):
        for attempt in range(retries + 1):
            repo.pull()
            try:
                repo._run(lambda: repo._git("revert", "--no-edit", sha))
            except VaultError as error:
                try:
                    repo._git("revert", "--abort")       # leave the clone clean; next pull resets anyway
                except Exception:
                    pass
                raise VaultError("conflict", "Откат невозможен: эти строки уже изменены после применения.") from error
            try:
                repo.push()
                return repo.head().strip()
            except VaultError as error:
                if error.kind != "conflict" or attempt == retries:
                    raise
        raise VaultError("conflict", "Не удалось отправить откат, попробуйте ещё раз.")
