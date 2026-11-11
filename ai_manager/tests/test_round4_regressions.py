"""Regression tests for the Round 4 review (docs/audit/round4/VERIFY.md, bugs B-52…B-57)."""
from unittest import mock

import pytest
from django.test import Client

from core import agent, frontmatter as fm, notes_service
from core.models import AgentBatch, ApiToken
from tests import vault_helpers as vh
from tests.acceptance.test_round4 import NOTE, ScriptedProvider, real_git, remote, vuser  # noqa: F401


def bearer(raw):
    return {"HTTP_AUTHORIZATION": f"Bearer {raw}"}


def test_b52_api_agent_never_auto_applies(vuser, remote):
    """H1: an ai-only token must not write through the 'apply additions automatically' option."""
    s = vuser.settings
    s.agent_auto_apply_additions = True
    s.save()
    _, ai_only = ApiToken.create_for(vuser, name="ai", scopes=["ai"])
    before = vh.remote_log(remote)
    prov = ScriptedProvider([{"tools": [("append_to_note", {"path": NOTE, "text": "инъекция"})]}, {"text": "ok"}])
    with mock.patch.object(agent, "default_provider", lambda user: prov):
        data = Client().post("/api/v1/agent/", data='{"request": "x"}', content_type="application/json",
                             **bearer(ai_only)).json()
    assert vh.remote_log(remote) == before and data["status"] == "pending"


def test_b53_api_revert_checks_paths(vuser, remote):
    """M1: revert via the API needs write (and delete for created notes) on every applied path."""
    prov = ScriptedProvider([{"tools": [("create_note", {"folder": "05 - Fleeting", "title": "Новая", "content": "x"})]},
                             {"text": "ok"}])
    run = agent.run_agent(vuser, "x", provider=prov)
    agent.apply_batch(vuser, run.batch.pk)
    _, bot = ApiToken.create_for(vuser, name="bot", scopes=["read", "write"], write_paths=["03 - Resources"])
    _, writer = ApiToken.create_for(vuser, name="w", scopes=["read", "write"])          # no delete scope
    c = Client()

    def revert(raw):
        return c.post(f"/api/v1/agent/{run.batch.pk}/revert/", data="{}", content_type="application/json", **bearer(raw))
    assert revert(bot).status_code == 403 and revert(writer).status_code == 403
    _, owner = ApiToken.create_for(vuser, name="o", scopes=["read", "write", "delete"])
    assert revert(owner).status_code == 200


def test_b54_partial_revert_is_not_repeated(vuser, monkeypatch):
    """M2: a revert that fails half-way keeps only the commits that are still applied."""
    batch = AgentBatch.objects.create(user=vuser, request="x", status="applied", changes=[], commits=["aaaaaaa", "bbbbbbb"])
    calls = []

    def fake_revert(user, sha):
        calls.append(sha)
        if sha == "aaaaaaa":
            raise agent.VaultError("conflict", "конфликт")
    monkeypatch.setattr(agent, "vault_revert", fake_revert)
    with pytest.raises(agent.AgentError):
        agent.revert_batch(vuser, batch.pk)
    batch.refresh_from_db()
    assert calls == ["bbbbbbb", "aaaaaaa"] and batch.commits == ["aaaaaaa"]


@pytest.mark.parametrize("value", ["Ответ: да", "#x", "[a", " lead", "true", '"в кавычках"', "a #b"])
def test_b55_frontmatter_values_are_yaml_safe(value):
    """M3: values that plain YAML would misread are quoted, and read back unchanged."""
    text = "---\ntype: digest\n---\nbody\n"
    out = fm.set_fields(text, {"title": value})
    line = [l for l in out.splitlines() if l.startswith("title:")][0]
    assert line.startswith('title: "') and fm.parse(out)["title"] == value
    assert fm.set_fields(text, {"status": "read"}) == "---\ntype: digest\nstatus: read\n---\nbody\n"
    assert fm.parse(fm.set_fields(text, {"tags": ["a, b", "c"]}))["tags"][1] == "c"


def test_b56_rename_keeps_crlf(vuser, remote, tmp_path):
    """M4: notes that link to the renamed note keep their CRLF line endings byte for byte."""
    import subprocess

    def stored():
        return subprocess.run(["git", "--git-dir", str(remote), "show", "main:05 - Fleeting/crlf.md"],
                              capture_output=True, check=True).stdout

    phone = vh.clone(remote, tmp_path / "phone")
    vh.git(phone, "config", "core.autocrlf", "false")          # store CRLF as is (like a Windows Obsidian)
    vh.commit_and_push(phone, "05 - Fleeting/crlf.md", "line one\r\n[[Университет]]\r\n")
    assert stored() == "line one\r\n[[Университет]]\r\n".encode("utf-8")
    notes_service.rename_note(vuser, "00 - Maps of content/Университет.md", "00 - Maps of content/Учёба.md")
    assert stored() == "line one\r\n[[Учёба]]\r\n".encode("utf-8")


def test_b57_rename_ambiguous_names_and_case(vuser, remote, tmp_path):
    """M5: bare links are not rewritten when another note has the same name; case-insensitive match."""
    phone = vh.clone(remote, tmp_path / "phone")
    vh.commit_and_push(phone, "07 - Archives/Университет.md", "старая\n")
    vh.commit_and_push(phone, "05 - Fleeting/ссылки.md",
                       "[[Университет]] [[00 - Maps of content/Университет]]\n")
    notes_service.rename_note(vuser, "00 - Maps of content/Университет.md", "00 - Maps of content/Учёба.md")
    assert vh.remote_file(remote, "05 - Fleeting/ссылки.md", tmp_path) == \
        "[[Университет]] [[00 - Maps of content/Учёба]]\n"
    assert notes_service._relink("[[университет|x]]", "A/Университет.md", "A/Учёба.md") == "[[Учёба|x]]"
