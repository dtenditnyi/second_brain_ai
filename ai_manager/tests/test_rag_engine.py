"""core.rag_engine with real LlamaIndex + Chroma (temp dir), but fake LLMs,
fake embeddings (conftest) and no network."""
from unittest import mock

import pytest
import requests
from llama_index.core.llms import MockLLM

from core import rag_engine

pytestmark = pytest.mark.django_db


class LLMFactory:
    """Records constructor kwargs and returns an offline MockLLM (echoes the prompt)."""

    def __init__(self):
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return MockLLM()


@pytest.fixture
def llms(monkeypatch):
    ollama, gemini = LLMFactory(), LLMFactory()
    monkeypatch.setattr(rag_engine, "Ollama", ollama)
    monkeypatch.setattr(rag_engine, "GoogleGenAI", gemini)
    return ollama, gemini


@pytest.fixture
def configured_user(user):
    s = user.settings
    s.github_repo_url = "https://github.com/u/vault.git"
    s.github_token = "tok"
    s.save()
    return user


@pytest.fixture
def fake_sync(monkeypatch):
    sync = mock.Mock(return_value=True)
    monkeypatch.setattr(rag_engine, "sync_obsidian_repo", sync)
    return sync


def set_local_online(monkeypatch, online):
    monkeypatch.setattr(rag_engine, "is_local_ai_ready", lambda timeout=3.0: online)


# --- helpers ----------------------------------------------------------------

def test_get_user_paths(user, isolated_vault):
    p = rag_engine.get_user_paths(user)
    assert p["notes_dir"].endswith(f"obsidian_data\\user_{user.id}") or p["notes_dir"].endswith(f"obsidian_data/user_{user.id}")
    assert p["collection_name"] == f"collection_user_{user.id}"


def test_is_local_ai_ready_true_on_200(monkeypatch):
    monkeypatch.setattr(rag_engine.requests, "get", lambda url, timeout: mock.Mock(status_code=200))
    assert rag_engine.is_local_ai_ready() is True


@pytest.mark.parametrize("code", [429, 500, 404])
def test_is_local_ai_ready_false_on_error_status(monkeypatch, code):
    monkeypatch.setattr(rag_engine.requests, "get", lambda url, timeout: mock.Mock(status_code=code))
    assert rag_engine.is_local_ai_ready() is False


def test_is_local_ai_ready_false_when_offline():
    assert rag_engine.is_local_ai_ready() is False  # conftest makes requests.get raise


def test_is_local_ai_ready_uses_timeout(monkeypatch):
    seen = {}

    def fake_get(url, timeout):
        seen.update(url=url, timeout=timeout)
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(rag_engine.requests, "get", fake_get)
    assert rag_engine.is_local_ai_ready(timeout=1.5) is False
    assert seen["timeout"] == 1.5 and seen["url"].endswith("/api/tags")


def test_reset_chat_engine_only_affects_that_user():
    rag_engine._user_chat_engines.update({1: "e1", 2: "e2"})
    rag_engine._user_indexes.update({1: "i1", 2: "i2"})
    rag_engine.reset_chat_engine(1)
    assert rag_engine._user_chat_engines == {2: "e2"} and rag_engine._user_indexes == {2: "i2"}


def test_reset_chat_engine_for_uncached_user_keeps_other_users_cache():
    """Saving settings for a user without a cached engine must not wipe everybody's cache."""
    rag_engine._user_chat_engines.update({2: "e2"})
    rag_engine._user_indexes.update({2: "i2", 3: "i3"})
    rag_engine._user_llms.update({2: "l2", 3: "l3"})
    rag_engine.reset_chat_engine(3)
    assert rag_engine._user_chat_engines == {2: "e2"}
    assert rag_engine._user_indexes == {2: "i2"}
    assert rag_engine._user_llms == {2: "l2"}


def test_reset_chat_engine_all():
    rag_engine._user_chat_engines.update({1: "e1"})
    rag_engine._user_indexes.update({1: "i1"})
    rag_engine.reset_chat_engine()
    assert rag_engine._user_chat_engines == {} and rag_engine._user_indexes == {}


# --- ask_second_brain ---------------------------------------------------------

def test_ask_without_repo_returns_notice(user, llms, fake_sync):
    assert rag_engine.ask_second_brain("q", user) == "System Notification: Please configure your GitHub link."
    fake_sync.assert_not_called()


def test_ask_local_only_offline_returns_error(configured_user, llms, fake_sync, monkeypatch):
    s = configured_user.settings
    s.ai_strategy = "local_only"
    s.save()
    set_local_online(monkeypatch, False)
    out = rag_engine.ask_second_brain("q", configured_user)
    assert out == "System Error: Local AI is strictly selected but the PC is offline"
    assert llms[0].calls == [] and llms[1].calls == []


@pytest.mark.parametrize("strategy,online,expected", [
    ("auto", True, "ollama"),
    ("auto", False, "gemini"),
    ("local_only", True, "ollama"),
    ("cloud_only", True, "gemini"),
    ("cloud_only", False, "gemini"),
])
def test_ask_routes_to_provider(configured_user, llms, fake_sync, monkeypatch, note_writer, strategy, online, expected):
    s = configured_user.settings
    s.ai_strategy, s.temperature = strategy, 0.3
    s.save()
    set_local_online(monkeypatch, online)
    note_writer(configured_user, "Fact", "The capital of Atlantis is Poseidonia.")
    out = rag_engine.ask_second_brain("What is the capital?", configured_user)
    ollama, gemini = llms
    used, unused = (ollama, gemini) if expected == "ollama" else (gemini, ollama)
    assert len(used.calls) == 1 and unused.calls == []
    assert used.calls[0]["temperature"] == pytest.approx(0.3)
    if expected == "ollama":
        assert used.calls[0]["model"] == "llama3:latest"
    else:
        assert used.calls[0]["model"].startswith("gemini")
    # MockLLM echoes its prompt: retrieved note context must have been injected.
    assert "Poseidonia" in out
    fake_sync.assert_called_once()


def test_ask_builds_index_once_and_caches(configured_user, llms, fake_sync, monkeypatch, note_writer):
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "A", "alpha content")
    rag_engine.ask_second_brain("q1", configured_user)
    rag_engine.ask_second_brain("q2", configured_user)
    assert fake_sync.call_count == 1
    assert len(llms[1].calls) == 1
    assert configured_user.id in rag_engine._user_indexes


def test_ask_provider_change_rebuilds_engine(configured_user, llms, fake_sync, monkeypatch, note_writer):
    note_writer(configured_user, "A", "alpha")
    set_local_online(monkeypatch, False)
    rag_engine.ask_second_brain("q1", configured_user)
    set_local_online(monkeypatch, True)
    rag_engine.ask_second_brain("q2", configured_user)
    assert len(llms[1].calls) == 1 and len(llms[0].calls) == 1
    assert fake_sync.call_count == 2


def test_ask_existing_collection_is_refreshed(configured_user, llms, fake_sync, monkeypatch, note_writer):
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "A", "first version")
    rag_engine.ask_second_brain("q", configured_user)
    rag_engine.reset_chat_engine(configured_user.id)
    note_writer(configured_user, "A", "second version mentions Zanzibar")
    out = rag_engine.ask_second_brain("q", configured_user)
    assert "Zanzibar" in out


def test_ask_selected_files_filter_restricts_context(configured_user, llms, fake_sync, monkeypatch, note_writer):
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "Keep", "KEEP-THIS-FACT")
    note_writer(configured_user, "Drop", "DROP-THIS-FACT")
    out = rag_engine.ask_second_brain("q", configured_user, ["Keep"])
    assert "KEEP-THIS-FACT" in out and "DROP-THIS-FACT" not in out
    out2 = rag_engine.ask_second_brain("q", configured_user, ["Drop.md"])
    assert "DROP-THIS-FACT" in out2 and "KEEP-THIS-FACT" not in out2


def test_ask_sync_failure_explains_instead_of_empty_response(configured_user, llms, fake_sync, monkeypatch, note_writer):
    """Q14: failed sync + empty index → a clear message (was LlamaIndex's "Empty Response")."""
    fake_sync.return_value = False
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "Local", "NOT-INDEXED-WHEN-SYNC-FAILS")
    out = rag_engine.ask_second_brain("my question", configured_user)
    assert out == rag_engine.MSG_SYNC_FAILED
    assert "Could not sync your vault with GitHub" in out and "Settings" in out
    assert llms[1].calls == []  # no LLM request is wasted


def test_ask_empty_vault_after_successful_sync(configured_user, llms, fake_sync, monkeypatch):
    set_local_online(monkeypatch, False)
    out = rag_engine.ask_second_brain("q", configured_user)
    assert out == rag_engine.MSG_INDEX_EMPTY and "index is empty" in out


def test_ask_sync_failure_with_existing_index_still_answers(configured_user, llms, fake_sync, monkeypatch, note_writer):
    """A failed pull must not hide notes that were indexed before."""
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "Old", "PREVIOUSLY-INDEXED")
    rag_engine.ask_second_brain("q", configured_user)
    rag_engine.reset_chat_engine(configured_user.id)
    fake_sync.return_value = False
    assert "PREVIOUSLY-INDEXED" in rag_engine.ask_second_brain("q", configured_user)


def test_ask_exception_is_reported_as_text(configured_user, fake_sync, monkeypatch, note_writer):
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "A", "a")

    def boom(**kw):
        raise ValueError("no api key")

    monkeypatch.setattr(rag_engine, "GoogleGenAI", boom)
    assert rag_engine.ask_second_brain("q", configured_user) == "System Error: no api key"


def test_ask_bad_temperature_falls_back(configured_user, llms, fake_sync, monkeypatch, note_writer):
    note_writer(configured_user, "A", "a")
    UserSettingsQS = type(configured_user.settings).objects
    UserSettingsQS.filter(id=configured_user.settings.id).update(temperature=0.9)
    configured_user.refresh_from_db()
    set_local_online(monkeypatch, False)
    configured_user.settings.temperature = "garbage"
    rag_engine.ask_second_brain("q", configured_user)
    assert llms[1].calls[0]["temperature"] == 0.7


def test_ask_includes_conversation_memory(configured_user, llms, fake_sync, monkeypatch, note_writer):
    """Q2: previous turns reach the model (MockLLM echoes the whole prompt)."""
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "A", "alpha")
    history = [("user", "My favourite colour is TEAL-42"), ("ai", "Noted, TEAL-42.")]
    out = rag_engine.ask_second_brain("What is my favourite colour?", configured_user, history=history)
    assert "TEAL-42" in out and out.index("TEAL-42") < out.index("What is my favourite colour?")


def test_load_chat_history_is_per_user_limited_and_skips_system_texts(user, other_user, settings):
    from core.models import ChatMessage
    settings.CHAT_HISTORY_MESSAGES = 4
    ChatMessage.objects.create(user=user, role="user", content="old question")
    ChatMessage.objects.create(user=user, role="ai", content="old answer")
    ChatMessage.objects.create(user=other_user, role="user", content="BOB-ONLY")
    ChatMessage.objects.create(user=user, role="user", content="q2")
    ChatMessage.objects.create(user=user, role="ai", content="System Error: boom")
    ChatMessage.objects.create(user=user, role="user", content="q3")
    ChatMessage.objects.create(user=user, role="ai", content="a3")
    hist = rag_engine.load_chat_history(user)
    assert hist == [("user", "q2"), ("user", "q3"), ("ai", "a3")]
    assert all("BOB-ONLY" not in text for _, text in hist)
    settings.CHAT_HISTORY_MESSAGES = 0
    assert rag_engine.load_chat_history(user) == []


def test_load_chat_history_never_starts_with_ai_turn(user):
    from core.models import ChatMessage
    for role, text in [("user", "u1"), ("ai", "a1"), ("user", "u2"), ("ai", "a2"),
                       ("user", "u3"), ("ai", "a3"), ("user", "u4")]:
        ChatMessage.objects.create(user=user, role=role, content=text)
    hist = rag_engine.load_chat_history(user, limit=6)  # would start with "a1"
    assert hist[0] == ("user", "u2") and len(hist) == 5


def test_build_messages_respects_token_budget_and_keeps_newest_history():
    chunks = ["C" * 6000] * 5            # ~1500 tokens each
    history = [("user", f"old-{i} " + "h" * 2000) if i % 2 == 0 else ("ai", f"ans-{i} " + "h" * 2000)
               for i in range(10)]       # ~500 tokens each
    msgs, used_chunks, used_hist = rag_engine.build_messages("SYS", chunks, history, "QUESTION", budget=8000)
    total = sum(rag_engine.estimate_tokens(m.content) for m in msgs)
    assert total <= 8000
    assert 0 < len(used_chunks) < 5
    assert used_hist and used_hist[-1] == history[-1] and used_hist[0][0] == "user"
    assert msgs[0].role.value == "system" and msgs[-1].content == "QUESTION"


def test_build_messages_inline_system_prompt_for_gemma():
    msgs, _, _ = rag_engine.build_messages("SYSTEM-RULES", ["chunk"], [("user", "hi"), ("ai", "yo")],
                                           "Q", budget=8000, inline_system=True)
    assert all(m.role.value != "system" for m in msgs)
    assert msgs[0].role.value == "user" and msgs[0].content.startswith("SYSTEM-RULES") and "chunk" in msgs[0].content


def test_oversized_single_chunk_is_truncated_not_dropped():
    msgs, used, _ = rag_engine.build_messages("S", ["X" * 100_000], [], "Q", budget=8000)
    assert len(used) == 1 and rag_engine.estimate_tokens(msgs[0].content) < 8000


@pytest.mark.parametrize("error,kind", [
    (Exception("429 RESOURCE_EXHAUSTED. Quota exceeded"), "quota"),
    (type("ClientError", (Exception,), {"code": 429})("rate"), "quota"),
    (Exception("404 NOT_FOUND models/foo is not found"), "unavailable"),
    (Exception("503 UNAVAILABLE"), "unavailable"),
    (ValueError("Missing key inputs argument"), None),
])
def test_classify_llm_error(error, kind):
    assert rag_engine.classify_llm_error(error) == kind


def test_ollama_url_from_settings_with_localhost_default(settings):
    settings.OLLAMA_HOST = "http://gpu-box:11434"
    assert rag_engine.ollama_url() == "http://gpu-box:11434"
    settings.OLLAMA_HOST = ""
    assert rag_engine.ollama_url() == "http://localhost:11434"
    import pathlib
    src = (pathlib.Path(rag_engine.__file__).resolve().parent.parent / "ai_manager" / "settings.py").read_text(encoding="utf-8")
    assert "OLLAMA_HOST = os.getenv('OLLAMA_HOST') or 'http://localhost:11434'" in src


def test_no_hardcoded_lan_ip_in_code():
    import pathlib
    root = pathlib.Path(rag_engine.__file__).resolve().parent.parent
    for path in list((root / "core").rglob("*.py")) + list((root / "ai_manager").glob("*.py")):
        assert "192.168." not in path.read_text(encoding="utf-8"), path


# --- Gemini fallback chain (section 3) ----------------------------------------

class QuotaError(Exception):
    code = 429


class ScriptedGemini:
    """GoogleGenAI stand-in: models listed in `fail` raise, others answer via MockLLM."""

    def __init__(self, fail=None, error=QuotaError("429 RESOURCE_EXHAUSTED")):
        self.fail, self.error, self.created, self.chatted = set(fail or ()), error, [], []

    def __call__(self, **kwargs):
        self.created.append(kwargs)
        outer, model = self, kwargs["model"]

        class _LLM(MockLLM):
            def chat(self, messages, **kw):
                outer.chatted.append((model, messages))
                if model in outer.fail:
                    raise outer.error
                return super().chat(messages, **kw)
        return _LLM()


@pytest.fixture
def chain(settings):
    settings.GEMINI_MODEL_DEFAULT = "gemini-3.5-flash-lite"
    settings.GEMINI_MODEL_SMART = "gemini-3.8-flash"
    settings.GEMINI_FALLBACK_MODELS = ["gemini-3.1-flash-lite", "gemma-4-31b-it"]
    return settings


def _cloud_user(user, strategy="cloud_only"):
    s = user.settings
    s.ai_strategy = strategy
    s.save()
    return user


def test_quota_on_first_model_falls_back_to_second(configured_user, chain, fake_sync, monkeypatch, note_writer):
    gem = ScriptedGemini(fail={"gemini-3.5-flash-lite"})
    monkeypatch.setattr(rag_engine, "GoogleGenAI", gem)
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "A", "FALLBACK-CONTEXT")
    out = rag_engine.ask_second_brain("q", _cloud_user(configured_user))
    assert "FALLBACK-CONTEXT" in out
    assert [m for m, _ in gem.chatted] == ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]
    configured_user.settings.refresh_from_db()
    assert configured_user.settings.last_model_used == "Gemini 3.1 Flash Lite"
    assert configured_user.settings.last_model_at is not None


def test_gemini_is_created_without_metadata_call_and_without_retries(configured_user, chain, fake_sync, monkeypatch, note_writer):
    gem = ScriptedGemini()
    monkeypatch.setattr(rag_engine, "GoogleGenAI", gem)
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "A", "a")
    rag_engine.ask_second_brain("q", configured_user)
    kw = gem.created[0]
    assert kw["model"] == "gemini-3.5-flash-lite"
    assert kw["max_retries"] == 0 and kw["max_tokens"] and kw["context_window"]


def test_smart_mode_starts_with_smart_model(configured_user, chain, fake_sync, monkeypatch, note_writer):
    gem = ScriptedGemini()
    monkeypatch.setattr(rag_engine, "GoogleGenAI", gem)
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "A", "a")
    rag_engine.ask_second_brain("q", configured_user, smart=True)
    assert gem.chatted[0][0] == "gemini-3.8-flash"


def test_gemma_fallback_gets_inline_system_prompt_and_small_budget(configured_user, chain, fake_sync, monkeypatch, note_writer):
    gem = ScriptedGemini(fail={"gemini-3.5-flash-lite", "gemini-3.1-flash-lite"})
    monkeypatch.setattr(rag_engine, "GoogleGenAI", gem)
    set_local_online(monkeypatch, False)
    for i in range(6):
        note_writer(configured_user, f"N{i}", f"note {i} " + "word " * 3000)
    history = [("user", "x " * 3000), ("ai", "y " * 3000)] * 3
    rag_engine.ask_second_brain("q", _cloud_user(configured_user), history=history)
    model, messages = gem.chatted[-1]
    assert model == "gemma-4-31b-it"
    assert all(m.role.value != "system" for m in messages)
    assert sum(rag_engine.estimate_tokens(m.content) for m in messages) <= 8000
    configured_user.settings.refresh_from_db()
    assert configured_user.settings.last_model_used == "Gemma 4 31B"


def test_all_models_exhausted_cloud_only_gives_clear_message(configured_user, chain, fake_sync, monkeypatch, note_writer, llms):
    gem = ScriptedGemini(fail={"gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemma-4-31b-it"})
    monkeypatch.setattr(rag_engine, "GoogleGenAI", gem)
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "A", "a")
    out = rag_engine.ask_second_brain("q", _cloud_user(configured_user))
    assert out == rag_engine.MSG_QUOTA and "daily limit" in out.lower()
    assert llms[0].calls == []  # no Ollama in Cloud Only


def test_all_models_exhausted_auto_hybrid_uses_ollama(configured_user, chain, fake_sync, monkeypatch, note_writer, llms):
    gem = ScriptedGemini(fail={"gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemma-4-31b-it"})
    monkeypatch.setattr(rag_engine, "GoogleGenAI", gem)
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "A", "OLLAMA-SAW-THIS")
    out = rag_engine.ask_second_brain("q", _cloud_user(configured_user, "auto"))
    assert "OLLAMA-SAW-THIS" in out and len(llms[0].calls) == 1
    configured_user.settings.refresh_from_db()
    assert configured_user.settings.last_model_used.startswith("Ollama")


def test_non_quota_error_is_not_masked_by_fallback(configured_user, chain, fake_sync, monkeypatch, note_writer):
    gem = ScriptedGemini(fail={"gemini-3.5-flash-lite"}, error=ValueError("bad request: invalid argument"))
    monkeypatch.setattr(rag_engine, "GoogleGenAI", gem)
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "A", "a")
    out = rag_engine.ask_second_brain("q", configured_user)
    assert out == "System Error: bad request: invalid argument"
    assert len(gem.chatted) == 1


def test_unavailable_models_message(configured_user, chain, fake_sync, monkeypatch, note_writer):
    gem = ScriptedGemini(fail={"gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemma-4-31b-it"},
                         error=Exception("404 NOT_FOUND"))
    monkeypatch.setattr(rag_engine, "GoogleGenAI", gem)
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "A", "a")
    assert rag_engine.ask_second_brain("q", _cloud_user(configured_user)) == rag_engine.MSG_MODELS_UNAVAILABLE


def test_fallback_is_logged_with_model_that_answered(configured_user, chain, fake_sync, monkeypatch, note_writer, caplog):
    gem = ScriptedGemini(fail={"gemini-3.5-flash-lite"})
    monkeypatch.setattr(rag_engine, "GoogleGenAI", gem)
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "A", "a")
    rag_engine.logger.propagate = True
    caplog.set_level("INFO", logger="core.rag_engine")
    try:
        rag_engine.ask_second_brain("q", configured_user)
    finally:
        rag_engine.logger.propagate = False
    assert "gemini-3.5-flash-lite failed (quota" in caplog.text
    assert "LLM answered: provider=gemini, model=gemini-3.1-flash-lite" in caplog.text


def test_import_does_not_load_embedding_model_eagerly():
    """Importing core.rag_engine must not download/load the HF model (slow start, network)."""
    import importlib
    import sys
    calls = []

    class Spy:
        def __init__(self, *a, **k):
            calls.append(1)

    with mock.patch.object(sys.modules["llama_index.embeddings.huggingface"], "HuggingFaceEmbedding", Spy):
        importlib.reload(rag_engine)
    try:
        assert calls == []
    finally:
        importlib.reload(rag_engine)


def test_each_user_keeps_own_llm(configured_user, other_user, monkeypatch, fake_sync, note_writer):
    """B-10: the LLM must be per user, not the process-global Settings.llm."""
    created = {"ollama": [], "gemini": []}

    def make(kind):
        def factory(**kw):
            llm = MockLLM()
            created[kind].append(llm)
            return llm
        return factory

    monkeypatch.setattr(rag_engine, "Ollama", make("ollama"))
    monkeypatch.setattr(rag_engine, "GoogleGenAI", make("gemini"))
    set_local_online(monkeypatch, True)
    a = configured_user
    sa = a.settings
    sa.ai_strategy = "cloud_only"
    sa.save()
    b = other_user
    sb = b.settings
    sb.ai_strategy, sb.github_repo_url = "local_only", "https://github.com/b/v.git"
    sb.save()
    note_writer(a, "A", "a")
    note_writer(b, "B", "b")

    rag_engine.ask_second_brain("q", a)
    rag_engine.ask_second_brain("q", b)
    rag_engine.ask_second_brain("q again", a)
    assert list(rag_engine._user_llms[a.id].values()) == [created["gemini"][0]]
    assert list(rag_engine._user_llms[b.id].values()) == [created["ollama"][0]]
    assert len(created["gemini"]) == 1 and len(created["ollama"]) == 1
    a.settings.refresh_from_db()
    b.settings.refresh_from_db()
    assert a.settings.last_model_used.startswith("Gemini") and b.settings.last_model_used.startswith("Ollama")
