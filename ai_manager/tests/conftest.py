"""Shared pytest fixtures.

External services are never contacted:
* the HuggingFace embedding model (loaded at import of core.rag_engine) is
  replaced by a deterministic MockEmbedding *before* Django imports the views;
* Ollama probe (requests.get), Gemini/Ollama LLM classes, Chroma and GitPython
  are patched per test;
* every test gets its own temporary vault / chroma directory, so the real
  obsidian_data/ and chroma_db/ folders are never read or written.
"""
import os
import sys
import types

# Playwright's sync API runs an event loop in the main thread; Django would
# otherwise refuse ORM calls made from fixtures in E2E tests.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

# --- Stub the HuggingFace embedding module before anything imports it. -------
from llama_index.core.embeddings import MockEmbedding  # noqa: E402


class _FakeHuggingFaceEmbedding(MockEmbedding):
    """Offline stand-in: 384-dim constant vectors, no download."""

    def __init__(self, model_name=None, **kwargs):
        super().__init__(embed_dim=384)


_fake_hf = types.ModuleType("llama_index.embeddings.huggingface")
_fake_hf.HuggingFaceEmbedding = _FakeHuggingFaceEmbedding
sys.modules["llama_index.embeddings.huggingface"] = _fake_hf

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_vault(tmp_path, monkeypatch):
    """Point rag_engine's BASE_DIR / DB_DIR to a temp folder for every test."""
    from core import rag_engine

    base = tmp_path / "app"
    (base / "obsidian_data").mkdir(parents=True)
    monkeypatch.setattr(rag_engine, "BASE_DIR", str(base))
    monkeypatch.setattr(rag_engine, "DB_DIR", str(base / "chroma_db"))
    rag_engine.reset_chat_engine()
    yield base
    rag_engine.reset_chat_engine()


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    """Fail loudly if code tries to reach GitHub or Ollama without a test-specific mock."""
    import requests
    from core import git_sync

    class _ForbiddenRepo:
        @staticmethod
        def clone_from(*a, **k):
            raise RuntimeError("network: git clone attempted in tests")

        def __init__(self, *a, **k):
            raise RuntimeError("network: git repo access attempted in tests")

    monkeypatch.setattr(git_sync, "Repo", _ForbiddenRepo)

    def _offline(*a, **k):
        raise requests.exceptions.ConnectionError("offline in tests")

    from core import rag_engine
    monkeypatch.setattr(rag_engine.requests, "get", _offline)


def write_note(vault_base, user, name, text):
    """Create `<name>.md` inside the user's vault (sub-folders allowed in name)."""
    folder = os.path.join(str(vault_base), "obsidian_data", f"user_{user.id}")
    path = os.path.join(folder, f"{name}.md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


@pytest.fixture
def note_writer(isolated_vault):
    return lambda user, name, text: write_note(isolated_vault, user, name, text)


PASSWORD = "Str0ng-Pass-123!"


@pytest.fixture
def password():
    return PASSWORD


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(username="alice", password=PASSWORD, email="alice@example.com")


@pytest.fixture
def other_user(django_user_model):
    return django_user_model.objects.create_user(username="bob", password=PASSWORD)


@pytest.fixture
def superuser(django_user_model):
    return django_user_model.objects.create_superuser(username="root", password=PASSWORD, email="root@example.com")


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def admin_client_(client, superuser):
    client.force_login(superuser)
    return client


@pytest.fixture
def post_json():
    def _post(client, url, payload=None, raw=None):
        import json
        body = raw if raw is not None else json.dumps(payload or {})
        return client.post(url, data=body, content_type="application/json")
    return _post
