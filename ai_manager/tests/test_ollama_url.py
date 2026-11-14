"""B-73: OLLAMA_HOST may hold the Ollama server's bind address (no scheme, 0.0.0.0)."""
import pytest

from ai_manager.settings import normalize_ollama_url


@pytest.mark.parametrize("raw, url", [
    (None, "http://localhost:11434"),
    ("", "http://localhost:11434"),
    ("0.0.0.0", "http://127.0.0.1:11434"),
    ("0.0.0.0:11434", "http://127.0.0.1:11434"),
    ("127.0.0.1:11434", "http://127.0.0.1:11434"),
    ("192.168.1.150", "http://192.168.1.150:11434"),
    ("http://192.168.1.150:11434/", "http://192.168.1.150:11434"),
    ("https://ollama.example.com:443", "https://ollama.example.com:443"),
])
def test_normalize_ollama_url(raw, url):
    assert normalize_ollama_url(raw) == url
