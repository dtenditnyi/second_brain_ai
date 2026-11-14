"""AI providers behind one interface (Round 4 / G-E1, G-E5).

``provider.chat(system, messages, tools=None) -> Reply`` for Gemini (fallback chain),
Ollama (local) and Claude (Anthropic API). Messages use one neutral format:

    {"role": "user", "content": str}
    {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args"}]}
    {"role": "tool", "tool_call_id": str, "name": str, "content": str}

``tools`` = list of {"name", "description", "parameters" (JSON schema)}.
The RAG chat (``rag_engine.ask_second_brain``) keeps its LlamaIndex pipeline for Gemini /
Ollama and uses ``ClaudeProvider`` for Claude; the agent uses ``get_provider``.
"""
from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field

import requests
from django.conf import settings

from . import ai_models

logger = logging.getLogger("core.ai_providers")

# Model IDs checked against docs.claude.com (DECISIONS D26).
CLAUDE_MODELS = [
    {"id": "claude-haiku-5-5", "name": "Claude Haiku 5.5"},
    {"id": "claude-sonnet-5-5", "name": "Claude Sonnet 5.5"},
]
CLAUDE_MODEL_IDS = {m["id"] for m in CLAUDE_MODELS}
MAX_OUTPUT_TOKENS = 2048


class ProviderError(Exception):
    """kind: 'quota' | 'unavailable' | 'error'."""

    def __init__(self, kind, message):
        super().__init__(message)
        self.kind = kind


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Reply:
    text: str = ""
    tool_calls: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)


def claude_available():
    return bool(getattr(settings, "ANTHROPIC_API_KEY", ""))


def claude_label(model):
    return next((m["name"] for m in CLAUDE_MODELS if m["id"] == model), model)


def _anthropic_client(key):  # patched in tests
    import anthropic
    return anthropic.Anthropic(api_key=key, max_retries=0)


def _genai_client():  # patched in tests
    from google import genai
    return genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def _classify(error):
    from .rag_engine import classify_llm_error
    return classify_llm_error(error)


# --------------------------------------------------------------------------- Claude

class ClaudeProvider:
    name, supports_tools = "claude", True

    def __init__(self, model=None):
        self.model = model if model in CLAUDE_MODEL_IDS else settings.ANTHROPIC_MODEL
        self.label = claude_label(self.model)

    @staticmethod
    def _messages(messages):
        out = []
        for m in messages:
            if m["role"] == "tool":
                block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
                if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list):
                    out[-1]["content"].append(block)          # parallel results go in one user turn
                else:
                    out.append({"role": "user", "content": [block]})
            elif m["role"] == "assistant" and m.get("tool_calls"):
                content = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                content += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]}
                            for c in m["tool_calls"]]
                out.append({"role": "assistant", "content": content})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        return out

    def chat(self, system, messages, tools=None):
        if not claude_available():
            raise ProviderError("unavailable", "Claude не настроен: нет ANTHROPIC_API_KEY.")
        # No temperature: current Claude models reject sampling parameters together (D26).
        kwargs = {"model": self.model, "max_tokens": MAX_OUTPUT_TOKENS, "system": system,
                  "messages": self._messages(messages)}
        if tools:
            kwargs["tools"] = [{"name": t["name"], "description": t["description"],
                                "input_schema": t["parameters"]} for t in tools]
        try:
            response = _anthropic_client(settings.ANTHROPIC_API_KEY).messages.create(**kwargs)
        except Exception as error:
            kind = _classify(error)
            raise ProviderError(kind or "error", f"Claude: {type(error).__name__}") from error
        text, calls = [], []
        for block in response.content or []:
            if getattr(block, "type", "") == "text":
                text.append(block.text)
            elif getattr(block, "type", "") == "tool_use":
                calls.append(ToolCall(id=block.id, name=block.name, args=dict(block.input or {})))
        usage = getattr(response, "usage", None)
        return Reply(text="".join(text), tool_calls=calls,
                     usage={"input_tokens": getattr(usage, "input_tokens", 0) or 0,
                            "output_tokens": getattr(usage, "output_tokens", 0) or 0})


# --------------------------------------------------------------------------- Gemini

class GeminiProvider:
    name, supports_tools = "gemini", True

    def __init__(self, chain):
        self.chain = list(chain)
        self.model = self.chain[0]
        self.label = ai_models.model_info(self.model)["name"]

    @staticmethod
    def _contents(messages):
        out = []
        for m in messages:
            if m["role"] == "tool":
                part = {"function_response": {"name": m["name"], "response": {"result": m["content"]}}}
                if out and out[-1]["role"] == "user" and "function_response" in out[-1]["parts"][0]:
                    out[-1]["parts"].append(part)
                else:
                    out.append({"role": "user", "parts": [part]})
            elif m["role"] == "assistant":
                parts = [{"text": m["content"]}] if m.get("content") else []
                parts += [{"function_call": {"name": c["name"], "args": c["args"]}} for c in m.get("tool_calls") or []]
                out.append({"role": "model", "parts": parts or [{"text": ""}]})
            else:
                out.append({"role": "user", "parts": [{"text": m["content"]}]})
        return out

    def _call(self, model, system, messages, tools):
        contents = self._contents(messages)
        config = {"max_output_tokens": MAX_OUTPUT_TOKENS}
        if ai_models.is_gemma(model):                  # no system instruction support
            contents[0]["parts"].insert(0, {"text": system})
        else:
            config["system_instruction"] = system
        if tools:
            config["tools"] = [{"function_declarations": [
                {"name": t["name"], "description": t["description"], "parameters": t["parameters"]} for t in tools]}]
            config["automatic_function_calling"] = {"disable": True}
        response = _genai_client().models.generate_content(model=model, contents=contents, config=config)
        text, calls = [], []
        candidates = getattr(response, "candidates", None) or []
        parts = getattr(getattr(candidates[0], "content", None), "parts", None) or [] if candidates else []
        for part in parts:
            fc = getattr(part, "function_call", None)
            if fc:
                calls.append(ToolCall(id=getattr(fc, "id", None) or uuid.uuid4().hex[:12], name=fc.name,
                                      args=dict(fc.args or {})))
            elif getattr(part, "text", None):
                text.append(part.text)
        meta = getattr(response, "usage_metadata", None)
        return Reply(text="".join(text), tool_calls=calls,
                     usage={"input_tokens": getattr(meta, "prompt_token_count", 0) or 0,
                            "output_tokens": getattr(meta, "candidates_token_count", 0) or 0})

    def chat(self, system, messages, tools=None):
        failures = []
        for model in self.chain:
            try:
                reply = self._call(model, system, messages, tools)
                self.model, self.label = model, ai_models.model_info(model)["name"]
                return reply
            except Exception as error:
                kind = _classify(error)
                if kind is None:
                    raise ProviderError("error", f"Gemini: {type(error).__name__}") from error
                failures.append(kind)
                logger.warning("Gemini model %s failed (%s); trying the next model.", model, kind)
        raise ProviderError("quota" if "quota" in failures else "unavailable",
                            "Дневной лимит облачных моделей исчерпан." if "quota" in failures
                            else "Ни одна модель Gemini не ответила.")


# --------------------------------------------------------------------------- Ollama

def ollama_supports_tools(model):
    base = (model or "").split(":")[0].lower()
    return any(base == m.lower() or base.startswith(m.lower()) for m in settings.OLLAMA_TOOL_MODELS)


class OllamaProvider:
    name = "ollama"

    def __init__(self, model=None):
        self.model = model or settings.OLLAMA_MODEL
        self.label = ai_models.ollama_label()
        self.supports_tools = ollama_supports_tools(self.model)

    def chat(self, system, messages, tools=None):
        from .rag_engine import ollama_url
        out = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "assistant" and m.get("tool_calls"):
                out.append({"role": "assistant", "content": m.get("content") or "",
                            "tool_calls": [{"function": {"name": c["name"], "arguments": c["args"]}}
                                           for c in m["tool_calls"]]})
            elif m["role"] == "tool":
                out.append({"role": "tool", "content": m["content"], "tool_name": m["name"]})
            else:
                out.append({"role": m["role"], "content": m["content"]})
        payload = {"model": self.model, "messages": out, "stream": False}
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
        try:
            response = requests.post(f"{ollama_url()}/api/chat", json=payload, timeout=600)
            response.raise_for_status()
            data = response.json()
        except Exception as error:
            raise ProviderError("unavailable", f"Ollama: {type(error).__name__}") from error
        message = data.get("message") or {}
        calls = [ToolCall(id=uuid.uuid4().hex[:12], name=c["function"]["name"],
                          args=dict(c["function"].get("arguments") or {}))
                 for c in message.get("tool_calls") or [] if c.get("function")]
        return Reply(text=message.get("content") or "", tool_calls=calls,
                     usage={"input_tokens": data.get("prompt_eval_count", 0), "output_tokens": data.get("eval_count", 0)})


# --------------------------------------------------------------------------- choice

def cloud_provider(user_settings, purpose="chat", smart=False):
    if (user_settings.cloud_provider or "gemini") == "claude" and claude_available():
        return ClaudeProvider(user_settings.claude_model or settings.ANTHROPIC_MODEL)
    if purpose == "agent":
        chain = []
        for model in [settings.GEMINI_MODEL_AGENT, *settings.GEMINI_FALLBACK_MODELS]:
            if model and model not in chain:
                chain.append(model)
    else:
        chain = ai_models.gemini_chain(smart=smart)
    return GeminiProvider(chain)


def get_provider(user, purpose="chat", smart=False):
    """The provider for this user's AI strategy (local_only / cloud_only / auto)."""
    from . import rag_engine
    from .models import get_user_settings
    s = get_user_settings(user)
    strategy = s.ai_strategy or "auto"
    if strategy == "local_only":
        return OllamaProvider()
    if strategy == "auto" and rag_engine.is_local_ai_ready():
        local = OllamaProvider()
        if purpose != "agent" or local.supports_tools:
            return local
    return cloud_provider(s, purpose=purpose, smart=smart)
