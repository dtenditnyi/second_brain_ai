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


def test_ask_sync_failure_still_answers(configured_user, llms, fake_sync, monkeypatch, note_writer):
    """If git sync fails, an empty collection is not filled from disk, but the LLM still answers."""
    fake_sync.return_value = False
    set_local_online(monkeypatch, False)
    note_writer(configured_user, "Local", "NOT-INDEXED-WHEN-SYNC-FAILS")
    out = rag_engine.ask_second_brain("my question", configured_user)
    assert len(llms[1].calls) == 1
    assert not out.startswith("System Error")
    assert "NOT-INDEXED-WHEN-SYNC-FAILS" not in out
    # characterization: with an empty index LlamaIndex answers "Empty Response"
    assert out == "Empty Response"


def test_ask_exception_is_reported_as_text(configured_user, fake_sync, monkeypatch):
    set_local_online(monkeypatch, False)

    def boom(**kw):
        raise ValueError("no api key")

    monkeypatch.setattr(rag_engine, "GoogleGenAI", boom)
    assert rag_engine.ask_second_brain("q", configured_user) == "System Error: no api key"


def test_ask_bad_temperature_falls_back(configured_user, llms, fake_sync, monkeypatch):
    UserSettingsQS = type(configured_user.settings).objects
    UserSettingsQS.filter(id=configured_user.settings.id).update(temperature=0.9)
    configured_user.refresh_from_db()
    set_local_online(monkeypatch, False)
    configured_user.settings.temperature = "garbage"
    rag_engine.ask_second_brain("q", configured_user)
    assert llms[1].calls[0]["temperature"] == 0.7


@pytest.mark.characterization
def test_ask_creates_new_engine_each_message(configured_user, llms, fake_sync, monkeypatch):
    """Q2: a fresh chat engine is created per message (no conversation memory)."""
    set_local_online(monkeypatch, False)
    rag_engine.ask_second_brain("q1", configured_user)
    e1 = rag_engine._user_chat_engines[configured_user.id]
    rag_engine.ask_second_brain("q2", configured_user)
    assert rag_engine._user_chat_engines[configured_user.id] is not e1


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


def test_each_user_keeps_own_llm(configured_user, other_user, monkeypatch, fake_sync):
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

    rag_engine.ask_second_brain("q", a)
    rag_engine.ask_second_brain("q", b)
    rag_engine.ask_second_brain("q again", a)
    assert rag_engine._user_chat_engines[a.id]._llm is created["gemini"][0]
    assert rag_engine._user_chat_engines[b.id]._llm is created["ollama"][0]
