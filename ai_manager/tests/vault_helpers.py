"""Real local git repositories for vault tests (no network).

``make_remote(tmp_path)`` creates a bare "GitHub" repository seeded with a small
fictional vault that mirrors the owner's PARA structure and note style;
``clone(remote, dest)`` makes an extra working copy ("Obsidian on the phone"),
``commit_and_push`` changes a file there and pushes.
"""
import os
import subprocess
from pathlib import Path

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test Phone", "GIT_AUTHOR_EMAIL": "phone@example.com",
    "GIT_COMMITTER_NAME": "Test Phone", "GIT_COMMITTER_EMAIL": "phone@example.com",
    "GIT_TERMINAL_PROMPT": "0",
}

TASKS_NOTE = "01 - Projects/🎯 Цели и планы/Задачи.md"

FIXTURE_VAULT = {
    "00 - Maps of content/Главная (Home).md": (
        "---\ntags: [planning]\ntype: moc\nstatus: active\ndate: 2026-09-01\naliases: [Home]\n---\n"
        "# 🏠 Главная\n\n> [!info] Карта хранилища\n> Отсюда всё начинается.\n\n"
        "- [[Университет]]\n- [[Проекты (MOC)]]\n"
    ),
    "00 - Maps of content/Университет.md": (
        "---\ntags: [university]\ntype: moc\nstatus: active\ndate: 2026-09-01\naliases: []\n---\n"
        "# 🎓 Университет\n\n| Предмет | Статус |\n|---|---|\n| Физика | 🔥 |\n\n🔗 [[Главная (Home)]]\n"
    ),
    "01 - Projects/🚀 Активные/Second Brain.md": (
        "---\ntags: [dev, ai]\ntype: project\nstatus: active\ndate: 2026-10-01\naliases: [SB]\n---\n"
        "# 🚀 Second Brain\n\n- [x] Аудит\n- [/] Round 3\n\n🔗 [[Проекты (MOC)]]\n"
    ),
    TASKS_NOTE: (
        "---\ntags: [planning]\ntype: tasks-db\nstatus: active\ndate: 2026-11-01\naliases: [Задачи, Tasks]\n---\n"
        "# 🎯 Задачи\n\nЛичный текст владельца — не трогать.\n\n"
        "```dataview\nTASK FROM \"01 - Projects\" WHERE !completed\n```\n\n"
        "## 📥 Входящие\n"
        "- [ ] Сдать лабу по физике 📅 2026-11-14 ⏫ #university ➕ 2026-11-11 🆔 t7k2m9\n"
        "- [/] Дописать отчёт 🔼 #dev 🆔 a1b2c3 ⏳ 2026-11-12\n"
        "    - [ ] подзадача без ID\n"
        "- [ ] Задача без ID #planning\n\n"
        "## ✅ Выполнено\n"
        "- [x] Купить книги #books 🆔 zz9yy8 ✅ 2026-11-05\n\n"
        "🔗 [[Главная (Home)]]\n"
    ),
    "06 - Daily/2026 by weeks/Year 2 Semester 1/Fifth week of 2nd year.md": (
        "---\ntags: [planning]\ntype: weekly\ndate: 2026-10-27\n---\n# Неделя 5\n\n- [ ] Повторить DSA\n"
    ),
    "99 - Templates/Template_Weekly.md": "---\ntype: weekly\n---\n# <% tp.date.now() %>\n",
    ".obsidian/app.json": "{}\n",
}


def git(cwd, *args, check=True):
    # quotepath=off: non-ASCII paths (Cyrillic note names) come back readable, not octal-escaped.
    return subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=cwd, env={**os.environ, **GIT_ENV},
                           capture_output=True, text=True, encoding="utf-8", check=check)


def make_remote(tmp_path, files=None, name="remote.git"):
    """Bare repository with one commit containing ``files`` (default: FIXTURE_VAULT)."""
    tmp_path = Path(tmp_path)
    remote = tmp_path / name
    git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    seed = tmp_path / (name + "-seed")
    git(tmp_path, "clone", str(remote), str(seed))
    for rel, text in (FIXTURE_VAULT if files is None else files).items():
        path = seed / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    git(seed, "add", "-A")
    git(seed, "commit", "-m", "seed vault")
    git(seed, "push", "origin", "HEAD:main")
    return remote


def clone(remote, dest):
    git(Path(dest).parent, "clone", str(remote), str(dest))
    return Path(dest)


def commit_and_push(repo, rel, text, message="edit from phone"):
    git(repo, "pull", "--rebase", "-q", check=False)
    path = Path(repo) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    git(repo, "add", "-A")
    git(repo, "commit", "-m", message)
    git(repo, "push", "origin", "HEAD:main")


def remote_file(remote, rel, tmp_path):
    """Content of ``rel`` at the remote's main branch."""
    out = subprocess.run(["git", "--git-dir", str(remote), "show", f"main:{rel}"],
                         capture_output=True, check=True)
    return out.stdout.decode("utf-8")


def remote_log(remote):
    out = subprocess.run(["git", "--git-dir", str(remote), "log", "--format=%an|%s", "main"],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return [line.split("|", 1) for line in out.stdout.strip().splitlines()]
