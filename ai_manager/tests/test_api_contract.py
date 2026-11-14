"""Link2Note contract tests (docs/link2note/API_CONTRACT.md + contract/*.json) on the Django client.

Real git against local bare repos; AI is mocked. Every endpoint of the contract, its error
codes and the Idempotency-Key rules (incl. a retry after a lost answer).
"""
import json
from pathlib import Path
from unittest import mock
from urllib.parse import quote

import pytest
from django.test import Client

from core import url_normalize
from core.models import ApiToken, IdempotencyRecord
from tests import vault_helpers as vh
from tests.acceptance.test_round4 import real_git, remote, vuser  # noqa: F401

CONTRACT = Path(__file__).resolve().parents[2] / "docs" / "link2note" / "contract"
CASES = json.loads((CONTRACT / "url_normalize_cases.json").read_text(encoding="utf-8"))["cases"]
TAGS = [t["tag"] for t in json.loads((CONTRACT / "allowed_tags.json").read_text(encoding="utf-8"))["tags"]]
BOT = "03 - Resources/📥 Из ссылок"
URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def md(url=URL, status="unread", tags="[dev]", body="Текст."):
    return (f"---\ntype: digest\nstatus: {status}\nsource: youtube\nurl: {url}\nauthor: Fireship\n"
            f"date_added: 2026-11-11\nread_minutes: 3\ntags: {tags}\n---\n# ⌨️ Хоткеи\n{body}\n")


@pytest.fixture
def bot(vuser, settings):
    _, raw = ApiToken.create_for(vuser, name="link2note", scopes=["read", "write", "delete", "ai"],
                                 write_paths=[BOT, settings.CAPTURE_INBOX_NOTE, vh.TASKS_NOTE], delete_paths=[BOT])
    return raw


class Api:
    def __init__(self, raw):
        self.c, self.raw = Client(), raw

    def __call__(self, method, path_, payload=None, key=None, **query):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {self.raw}"}
        if key:
            headers["HTTP_IDEMPOTENCY_KEY"] = key
        if query:
            path_ += "?" + "&".join(f"{k.replace('__', '.')}={quote(str(v))}" for k, v in query.items())
        if payload is None:
            return getattr(self.c, method)(path_, **headers)
        return getattr(self.c, method)(path_, data=json.dumps(payload, ensure_ascii=False),
                                       content_type="application/json", **headers)


def note_url(path):
    return "/api/v1/notes/" + quote(path, safe="/")


def err(resp):
    body = resp.json()
    assert set(body["error"]) == {"code", "message", "retryable"}, body
    return body["error"]["code"]


# --------------------------------------------------------------------------- shared contract files

@pytest.mark.parametrize("case", CASES, ids=[c["url"][:60] for c in CASES])
def test_url_normalize_cases(case):
    assert url_normalize.normalize(case["url"]) == case["key"]


def test_allowed_tags_include_contract_tags(settings):
    from core import tasks_md
    assert set(TAGS) <= set(settings.ALLOWED_TAGS) and set(TAGS) <= set(tasks_md.ALLOWED_TAGS) and "fun" in TAGS


# --------------------------------------------------------------------------- auth / errors

def test_health_public_and_auth_errors(vuser, bot):
    r = Client().get("/api/v1/health")
    assert r.status_code == 200 and {"status", "vault_synced_at", "version"} <= set(r.json())
    assert err(Api("sb_nope")("get", "/api/v1/notes")) == "unauthorized"
    _, read_only = ApiToken.create_for(vuser, name="ro", scopes=["read"])
    r = Api(read_only)("post", "/api/v1/ask", {"question": "x"})
    assert r.status_code == 403 and err(r) == "forbidden"


def test_rate_limit_has_retry_after(vuser, settings):
    settings.API_RATE_LIMIT_PER_MINUTE = 1
    _, raw = ApiToken.create_for(vuser, name="r", scopes=["read"])
    api = Api(raw)
    api("get", "/api/v1/sync")
    r = api("get", "/api/v1/sync")
    assert r.status_code == 429 and err(r) == "rate_limited" and int(r["Retry-After"]) >= 1
    assert r.json()["error"]["retryable"] is True


# --------------------------------------------------------------------------- notes

def test_create_writes_markdown_as_is_and_suffixes_names(bot, remote, tmp_path):
    api = Api(bot)
    r = api("post", "/api/v1/notes", {"folder": BOT, "name": "2026-11-11 Хоткеи", "content": md(),
                                      "source": {"url": URL, "kind": "youtube"}})
    assert r.status_code == 201, r.content
    data = r.json()
    assert data["path"] == f"{BOT}/2026-11-11 Хоткеи.md" and data["pushed"] is True and data["commit"] and data["sha"]
    assert vh.remote_file(remote, data["path"], tmp_path) == md()
    r2 = api("post", "/api/v1/notes", {"folder": BOT, "name": "2026-11-11 Хоткеи", "content": md()})
    assert r2.json()["name"] == "2026-11-11 Хоткеи (2)"
    r3 = api("post", "/api/v1/notes", {"folder": BOT, "name": "x" * 120, "content": md()})
    assert r3.status_code == 201, r3.content.decode()


@pytest.mark.parametrize("payload,status", [
    ({"name": "x" * 121}, 422), ({"name": "a: b"}, 422), ({"name": "a/b"}, 422), ({"name": ""}, 422),
    ({"content": md(tags="[hacking]")}, 422), ({"content": md(tags="[dev, ai, fun, books]")}, 422),
    ({"content": md(status="new")}, 422), ({"content": "# без frontmatter\n"}, 422),
    ({"content": md().replace(f"url: {URL}\n", "")}, 422),
    ({"folder": "01 - Projects"}, 403), ({"folder": BOT + "2"}, 403), ({"folder": f"{BOT}/../01 - Projects"}, 400),
    ({"folder": ".obsidian"}, 400), ({"folder": "C:/x"}, 400), ({"folder": "a\\b"}, 400),
])
def test_create_validation(bot, remote, payload, status):
    body = {"folder": BOT, "name": "Note", "content": md(), **payload}
    before = vh.remote_log(remote)
    r = Api(bot)("post", "/api/v1/notes", body)
    assert r.status_code == status, r.content
    assert err(r) == {400: "validation_error", 403: "forbidden", 422: "validation_error"}[status]
    assert vh.remote_log(remote) == before


def test_fun_tag_allowed(bot):
    assert Api(bot)("post", "/api/v1/notes", {"folder": BOT, "name": "Fun", "content": md(tags="[fun]")}).status_code == 201


def test_lookup_read_list_patch_put_delete(bot, remote, tmp_path):
    api = Api(bot)
    path = api("post", "/api/v1/notes", {"folder": BOT, "name": "2026-11-11 Хоткеи", "content": md()}).json()["path"]
    api("post", "/api/v1/notes", {"folder": BOT, "name": "2026-11-01 Старая",
                                  "content": md(url="https://habr.com/ru/articles/1").replace("2026-11-11", "2026-11-01")})
    # lookup — any form of the link, nothing found = 200 []
    for variant in ("https://youtu.be/dQw4w9WgXcQ?si=x", URL + "&utm_source=tg", "https://m.youtube.com/watch?v=dQw4w9WgXcQ#x"):
        assert [i["path"] for i in api("get", "/api/v1/notes/lookup", url=variant).json()["items"]] == [path]
    assert api("get", "/api/v1/notes/lookup", url="https://example.com/none").json() == {"items": []}
    # read by percent-encoded path
    note = api("get", note_url(path)).json()
    assert note["content"] == md() and note["frontmatter"]["tags"] == ["dev"] and note["name"] == "2026-11-11 Хоткеи"
    assert note["frontmatter"]["read_minutes"] == "3"
    assert err(api("get", note_url(f"{BOT}/нет.md"))) == "not_found"
    assert api("get", note_url(".obsidian/app.md")).status_code == 400
    # list with frontmatter filter, sort, title
    items = api("get", "/api/v1/notes", folder=BOT, fm__type="digest", fm__status="unread", sort="fm.date_added").json()["items"]
    assert [i["name"] for i in items] == ["2026-11-01 Старая", "2026-11-11 Хоткеи"] and items[0]["title"] == "⌨️ Хоткеи"
    assert len(api("get", "/api/v1/notes", folder=BOT, sort="-fm.date_added", limit=1).json()["items"]) == 1
    # PATCH frontmatter: only that line changes, byte for byte
    r = api("patch", note_url(path) + "/frontmatter", {"set": {"status": "read"}, "if_sha": note["sha"]})
    assert r.status_code == 200, r.content
    assert vh.remote_file(remote, path, tmp_path) == md(status="read")
    commits = len(vh.remote_log(remote))
    r2 = api("patch", note_url(path) + "/frontmatter", {"set": {"status": "read"}})
    assert r2.status_code == 200 and len(vh.remote_log(remote)) == commits and r2.json()["commit"]
    assert err(api("patch", note_url(path) + "/frontmatter", {"set": {"status": "read"}, "if_sha": "0" * 40})) == "conflict"
    assert api("patch", note_url(path) + "/frontmatter", {"set": {"status": "weird"}}).status_code == 422
    assert api("patch", note_url(vh.TASKS_NOTE.replace("Задачи", "Нет")) + "/frontmatter", {"set": {"a": "b"}}).status_code == 403
    # PUT needs if_sha; a stale one → 409 + current_sha
    current = api("get", note_url(path)).json()["sha"]
    assert api("put", note_url(path), {"content": md(body="Новое.")}).status_code == 422
    stale = api("put", note_url(path), {"content": md(body="x"), "if_sha": "0" * 40})
    assert stale.status_code == 409 and stale.json()["current_sha"] == current and stale.json()["error"]["retryable"]
    r = api("put", note_url(path), {"content": md(status="read", body="Подробно."), "if_sha": current})
    assert r.status_code == 200 and vh.remote_file(remote, path, tmp_path) == md(status="read", body="Подробно.")
    # DELETE only in delete_paths; stays in git history
    assert api("delete", note_url(path) + "?if_sha=" + "0" * 40).status_code == 409
    assert api("delete", note_url(path)).status_code == 204
    assert api("get", note_url(path)).status_code == 404 and api("delete", note_url(path)).status_code == 404
    assert any(f"api: delete {path}" == m for _, m in vh.remote_log(remote))
    r = api("delete", note_url("00 - Maps of content/Университет.md"))
    assert r.status_code == 403 and err(r) == "forbidden"


def test_lookup_finds_moved_note(bot, remote, tmp_path):
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, "07 - Archives/Перенесена.md", md(url="https://www.instagram.com/reel/C1abc-_9/"))
    items = Api(bot)("get", "/api/v1/notes/lookup", url="https://instagram.com/reels/C1abc-_9?igsh=1").json()["items"]
    assert [i["path"] for i in items] == ["07 - Archives/Перенесена.md"]


# --------------------------------------------------------------------------- idempotency

def test_idempotency_same_request_by_meaning(bot, remote, vuser):
    api = Api(bot)
    body = {"folder": BOT, "name": "Ключ", "content": md()}
    first = api("post", "/api/v1/notes", body, key="k-1")
    before = len(vh.remote_log(remote))
    # the answer was "lost": the bot repeats — keys reordered / different escaping, same meaning
    raw = json.dumps(dict(reversed(list(body.items()))), ensure_ascii=True)
    again = api.c.post("/api/v1/notes", data=raw, content_type="application/json",
                       HTTP_AUTHORIZATION=f"Bearer {bot}", HTTP_IDEMPOTENCY_KEY="k-1")
    assert again.status_code == 201 and again.json() == first.json() and again["Idempotent-Replayed"] == "true"
    assert len(vh.remote_log(remote)) == before
    r = api("post", "/api/v1/notes", {**body, "name": "Другое"}, key="k-1")
    assert r.status_code == 409 and err(r) == "idempotency_mismatch" and r.json()["error"]["retryable"] is False
    # 4xx answers are final too; keys live per token
    assert api("post", "/api/v1/notes", {**body, "folder": "01 - Projects"}, key="k-2").status_code == 403
    assert api("post", "/api/v1/notes", {**body, "folder": "01 - Projects"}, key="k-2").status_code == 403
    _, other = ApiToken.create_for(vuser, name="o", scopes=["read", "write"])
    assert Api(other)("post", "/api/v1/notes", {**body, "name": "Чужой ключ"}, key="k-1").status_code == 201
    record = IdempotencyRecord.objects.get(key="k-1", token__name="link2note")
    assert not record.in_progress and "Ключ" in record.body


def test_idempotency_does_not_cache_5xx_and_reports_in_progress(bot, remote, tmp_path, monkeypatch):
    from core import vault_writer
    api = Api(bot)
    body = {"folder": BOT, "name": "Сбой", "content": md()}
    real = vault_writer.VaultRepo.pull
    monkeypatch.setattr(vault_writer.VaultRepo, "pull",
                        lambda self: (_ for _ in ()).throw(vault_writer.VaultError("offline", "no network")))
    r = api("post", "/api/v1/notes", body, key="k-5xx")
    assert r.status_code == 503 and err(r) == "vault_unavailable" and r["Retry-After"]
    assert not IdempotencyRecord.objects.filter(key="k-5xx").exists()
    monkeypatch.setattr(vault_writer.VaultRepo, "pull", real)
    assert api("post", "/api/v1/notes", body, key="k-5xx").status_code == 201        # executed now
    assert "Сбой.md" in vh.git(tmp_path, "--git-dir", str(remote), "ls-tree", "-r", "--name-only", "main").stdout
    # a repeat while the first request with this key is still running → 409 in_progress
    IdempotencyRecord.objects.filter(key="k-5xx").update(in_progress=True)
    r = api("post", "/api/v1/notes", body, key="k-5xx")
    assert r.status_code == 409 and err(r) == "in_progress" and r.json()["error"]["retryable"] is True


# --------------------------------------------------------------------------- capture / tasks / ask

def test_capture_inbox_and_weekly(bot, remote, tmp_path, settings):
    api = Api(bot)
    r = api("post", "/api/v1/capture", {"text": "идея: бот для Anki", "target": "inbox", "source": {"kind": "telegram"}})
    assert r.status_code == 201 and r.json()["path"] == settings.CAPTURE_INBOX_NOTE and r.json()["pushed"]
    inbox = vh.remote_file(remote, settings.CAPTURE_INBOX_NOTE, tmp_path)
    assert "идея: бот для Anki" in inbox and inbox.rstrip().endswith("🔗 [[Главная (Home)]]") and inbox.startswith("---\n")
    r = api("post", "/api/v1/capture", {"text": "в неделю", "target": "weekly"})
    assert r.status_code == 403                    # the weekly note is outside the bot's write_paths
    assert api("post", "/api/v1/capture", {"text": "", "target": "inbox"}).status_code == 422
    assert api("post", "/api/v1/capture", {"text": "x" * 10001, "target": "inbox"}).status_code == 422


def test_tasks_contract_shape(bot, remote, tmp_path):
    api = Api(bot)
    r = api("post", "/api/v1/tasks", {"text": "сдать лабу", "due": "2026-11-13", "priority": "high", "tags": ["university"]})
    assert r.status_code == 201
    task = r.json()
    assert {k: task[k] for k in ("text", "status", "due", "priority", "tags", "path")} == {
        "text": "сдать лабу", "status": "open", "due": "2026-11-13", "priority": "high", "tags": ["university"],
        "path": vh.TASKS_NOTE}
    assert api("post", "/api/v1/tasks", {"text": "x"}).json()["priority"] == "normal"
    assert task["id"] in [t["id"] for t in api("get", "/api/v1/tasks", status="open", due_before="2026-11-15").json()["items"]]
    assert api("patch", f"/api/v1/tasks/{task['id']}", {"status": "done"}).json()["status"] == "done"
    assert task["id"] not in [t["id"] for t in api("get", "/api/v1/tasks", status="open").json()["items"]]
    assert api("delete", f"/api/v1/tasks/{task['id']}").status_code == 204
    assert api("delete", f"/api/v1/tasks/{task['id']}").status_code == 404
    assert api("post", "/api/v1/tasks", {"text": "x", "tags": ["hacking"]}).status_code == 422
    assert api("post", "/api/v1/tasks", {"text": "x", "priority": "asap"}).status_code == 422
    assert api("post", "/api/v1/tasks", {"text": "x", "due": "13.11.2026"}).status_code == 422


def test_ask_contract(bot, vuser, note_writer):
    api = Api(bot)
    with mock.patch("core.rag_engine.ask_second_brain", return_value="**Docker** — контейнеры") as ask:
        r = api("post", "/api/v1/ask", {"question": "что я знаю про Docker?", "provider": None})
    assert r.status_code == 200 and r.json()["answer_markdown"] == "**Docker** — контейнеры"
    assert isinstance(r.json()["sources"], list) and ask.call_args.kwargs["provider"] is None
    with mock.patch("core.rag_engine.ask_second_brain", return_value="System Error: offline"):
        r = api("post", "/api/v1/ask", {"question": "x"})
    assert r.status_code == 503 and r.json()["error"]["retryable"] is True
    assert api("post", "/api/v1/ask", {"question": ""}).status_code == 422


def test_agent_apply_respects_write_paths(bot, vuser):
    from core import agent
    from tests.acceptance.test_round4 import NOTE, ScriptedProvider
    prov = ScriptedProvider([{"tools": [("append_to_note", {"path": NOTE, "text": "x"})]}, {"text": "ok"}])
    api = Api(bot)
    with mock.patch.object(agent, "default_provider", lambda user: prov):
        batch = api("post", "/api/v1/agent", {"request": "x"}).json()["batch_id"]
    r = api("post", f"/api/v1/agent/{batch}/apply", {})
    assert r.status_code == 403 and err(r) == "forbidden"     # NOTE is outside the bot's write_paths


def test_retry_after_push_that_landed_but_timed_out_does_not_duplicate(bot, remote, tmp_path, monkeypatch):
    """R4.5: the push reached the remote, but the site saw a timeout → 503 (not cached) → the bot
    retries with the same Idempotency-Key → the same note is returned, no « (2)» copy."""
    from core import vault_writer
    real_push = vault_writer.VaultRepo.push

    def push_then_timeout(self):
        real_push(self)
        raise vault_writer.VaultError("offline", "push timed out")

    api = Api(bot)
    payload = {"folder": BOT, "name": "2026-11-11 Таймаут", "content": md()}
    monkeypatch.setattr(vault_writer.VaultRepo, "push", push_then_timeout)
    assert api("post", "/api/v1/notes", payload, key="k-timeout").status_code == 503
    monkeypatch.setattr(vault_writer.VaultRepo, "push", real_push)
    r = api("post", "/api/v1/notes", payload, key="k-timeout")
    assert r.status_code == 201 and r.json()["name"] == "2026-11-11 Таймаут"
    files = vh.git(remote, "ls-tree", "-r", "--name-only", "main").stdout.splitlines()
    assert [f for f in files if "Таймаут" in f] == [f"{BOT}/2026-11-11 Таймаут.md"]
    # a different key with the same name is a new note, as the contract says
    assert api("post", "/api/v1/notes", payload, key="k-other").json()["name"] == "2026-11-11 Таймаут (2)"
