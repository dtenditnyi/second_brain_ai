"""Unit tests: core/ai_providers.py (message formats, choice, errors) and the agent session endpoints."""
import json
from unittest import mock

import pytest
from django.test import Client

from core import agent, ai_providers
from tests import vault_helpers as vh
from tests.acceptance.test_round4 import NOTE, ScriptedProvider, post, real_git, remote, vuser  # noqa: F401

CONVO = [
    {"role": "user", "content": "q"},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "name": "read_note", "args": {"path": "x.md"}},
                                                       {"id": "b", "name": "list_folder", "args": {}}]},
    {"role": "tool", "tool_call_id": "a", "name": "read_note", "content": "<note>1</note>"},
    {"role": "tool", "tool_call_id": "b", "name": "list_folder", "content": "<results/>"},
]


def test_claude_messages_group_parallel_tool_results():
    out = ai_providers.ClaudeProvider._messages(CONVO)
    assert [m["role"] for m in out] == ["user", "assistant", "user"]
    assert [b["type"] for b in out[1]["content"]] == ["tool_use", "tool_use"]
    assert [b["tool_use_id"] for b in out[2]["content"]] == ["a", "b"]


def test_gemini_contents_group_function_responses():
    out = ai_providers.GeminiProvider._contents(CONVO)
    assert [m["role"] for m in out] == ["user", "model", "user"]
    assert len(out[2]["parts"]) == 2 and "function_response" in out[2]["parts"][0]


def test_claude_tool_use_reply_and_errors(settings, monkeypatch):
    settings.ANTHROPIC_API_KEY = "k"
    block = mock.Mock(type="tool_use", id="t1", input={"path": "a.md"})
    block.name = "read_note"
    resp = mock.Mock(content=[block], usage=mock.Mock(input_tokens=3, output_tokens=1))
    monkeypatch.setattr(ai_providers, "_anthropic_client", lambda key: mock.Mock(messages=mock.Mock(create=lambda **kw: resp)))
    reply = ai_providers.ClaudeProvider("bogus-model").chat("s", [{"role": "user", "content": "q"}], tools=agent.TOOL_SPECS)
    assert reply.tool_calls[0].name == "read_note" and reply.usage == {"input_tokens": 3, "output_tokens": 1}

    def boom(**kw):
        raise Exception("429 rate limit")
    monkeypatch.setattr(ai_providers, "_anthropic_client", lambda key: mock.Mock(messages=mock.Mock(create=boom)))
    with pytest.raises(ai_providers.ProviderError) as err:
        ai_providers.ClaudeProvider().chat("s", [{"role": "user", "content": "q"}])
    assert err.value.kind == "quota"
    settings.ANTHROPIC_API_KEY = ""
    with pytest.raises(ai_providers.ProviderError):
        ai_providers.ClaudeProvider().chat("s", [])


def test_ollama_tool_support_and_reply(settings, monkeypatch):
    settings.OLLAMA_TOOL_MODELS = ["llama3.1", "qwen2.5"]
    assert ai_providers.ollama_supports_tools("qwen2.5:7b") and not ai_providers.ollama_supports_tools("gemma2:9b")
    resp = mock.Mock(json=lambda: {"message": {"content": "", "tool_calls": [{"function": {"name": "list_folder", "arguments": {}}}]},
                                   "prompt_eval_count": 4, "eval_count": 2}, raise_for_status=lambda: None)
    monkeypatch.setattr(ai_providers.requests, "post", lambda *a, **k: resp)
    reply = ai_providers.OllamaProvider("qwen2.5").chat("s", CONVO, tools=agent.TOOL_SPECS)
    assert reply.tool_calls[0].name == "list_folder" and reply.usage["input_tokens"] == 4


@pytest.mark.django_db
def test_get_provider_choice(user, settings):
    settings.ANTHROPIC_API_KEY = "k"
    s = user.settings
    s.ai_strategy, s.cloud_provider, s.claude_model = "cloud_only", "claude", "claude-sonnet-5-5"
    s.save()
    prov = ai_providers.get_provider(user, purpose="agent")
    assert isinstance(prov, ai_providers.ClaudeProvider) and prov.model == "claude-sonnet-5-5"
    settings.ANTHROPIC_API_KEY = ""                       # no key → Gemini, never a broken Claude
    assert isinstance(ai_providers.get_provider(user, purpose="agent"), ai_providers.GeminiProvider)
    s.ai_strategy = "auto"
    s.save()
    settings.OLLAMA_MODEL = "gemma2:9b"
    with mock.patch("core.rag_engine.is_local_ai_ready", return_value=True):
        # auto + local model without tools → the agent uses the cloud instead
        assert isinstance(ai_providers.get_provider(user, purpose="agent"), ai_providers.GeminiProvider)
        assert isinstance(ai_providers.get_provider(user, purpose="chat"), ai_providers.OllamaProvider)


def test_agent_endpoints_flow_and_isolation(vuser, remote, tmp_path, other_user):
    c = Client(enforce_csrf_checks=False)
    c.force_login(vuser)
    prov = ScriptedProvider([{"tools": [("append_to_note", {"path": NOTE, "text": "из API сессии"})]}, {"text": "ok"}])
    with mock.patch.object(agent, "default_provider", lambda user: prov):
        data = post(c, "/api/agent/run/", {"message": "Допиши"}).json()
    batch_id = data["batch"]["id"]
    assert data["batch"]["status"] == "pending" and data["steps"][0]["tool"] == "append_to_note"
    other = Client()
    other.force_login(other_user)
    assert post(other, f"/api/agent/batch/{batch_id}/apply/", {}).status_code == 404     # not their batch
    assert post(c, f"/api/agent/batch/{batch_id}/apply/", {"indices": "x"}).status_code == 400
    r = post(c, f"/api/agent/batch/{batch_id}/apply/", {"indices": [0]})
    assert r.status_code == 200 and r.json()["batch"]["status"] == "applied"
    assert "из API сессии" in vh.remote_file(remote, NOTE, tmp_path)
    assert post(c, f"/api/agent/batch/{batch_id}/reject/", {}).status_code == 409
    assert post(c, f"/api/agent/batch/{batch_id}/revert/", {}).json()["batch"]["status"] == "reverted"
    assert c.get("/api/agent/run/").status_code == 405
    assert post(c, "/api/agent/run/", {"message": "  "}).status_code == 400


def test_agent_endpoints_need_csrf(vuser):
    c = Client(enforce_csrf_checks=True)
    c.force_login(vuser)
    r = c.post("/api/agent/run/", data=json.dumps({"message": "x"}), content_type="application/json")
    assert r.status_code == 403
