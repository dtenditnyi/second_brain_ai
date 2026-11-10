# RAG and hybrid inference orchestration for the Second Brain application.
# This module synchronizes each user's Markdown vault, maintains a per-user
# Chroma-backed vector index, applies optional filename filters, and routes
# generation to either the user's local Ollama service or Google Gemini.
# Django views call ask_second_brain(); Git operations are delegated to
# git_sync.py, while LlamaIndex provides embeddings, the vector store and LLMs.
#
# Round 2:
# * conversation memory — the last N messages of the same user are sent along
#   (load_chat_history); history and note chunks are cut to a token budget;
# * Gemini fallback chain — on 429 / RESOURCE_EXHAUSTED / unavailable model the
#   next model of the chain is tried, then (Auto-Hybrid only) local Ollama;
# * explicit messages when the vault sync failed or the index is empty;
# * the model that really answered is logged and stored per user.
import os
import time
import requests
import logging
import chromadb
from django.conf import settings as django_settings
from django.utils import timezone
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, StorageContext, Settings
from llama_index.core.llms import ChatMessage as LLMMessage, MessageRole
from llama_index.core.vector_stores.types import ExactMatchFilter, FilterCondition, MetadataFilters
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.llms.google_genai import GoogleGenAI
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from .git_sync import sync_obsidian_repo
from . import ai_models

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, 'chroma_db')

# Use the centralized Django logging configuration for the dedicated RAG log file.
logger = logging.getLogger(__name__)

# Per-user runtime caches; reset_chat_engine invalidates them after settings change.
# _user_chat_engines holds the session state (provider mode, sync result, index size).
_user_chat_engines = {}
_user_indexes = {}
# Per-user LLM instances (B-10): {user_id: {(provider, model): llm}}. The global
# Settings.llm is shared by every user of the process and must not be used.
_user_llms = {}

# Use the same 384-dimensional embedding model for indexing and query vectors.
# The model is loaded lazily on the first chat request (B-15).
EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_embed_model_loaded = False

# Retrieval sizes: Gemma has only 16K tokens/minute, so it gets fewer chunks.
SIMILARITY_TOP_K = 5
SIMILARITY_TOP_K_GEMMA = 3

# User-facing texts. Everything that is not a real answer starts with "System "
# so it is never fed back to the model as conversation memory.
MSG_NO_REPO = "System Notification: Please configure your GitHub link."
MSG_LOCAL_OFFLINE = "System Error: Local AI is strictly selected but the PC is offline"
MSG_SYNC_FAILED = ("System Notification: Could not sync your vault with GitHub — "
                   "check the repository URL and token in Settings.")
MSG_INDEX_EMPTY = ("System Notification: Your vault index is empty — no Markdown (.md) "
                   "notes were found in the repository.")
MSG_QUOTA = ("System Notification: The daily limit of the cloud models is exhausted — "
             "try again later or switch to local mode (Ollama) in Settings.")
MSG_MODELS_UNAVAILABLE = ("System Error: none of the configured Gemini models answered — "
                          "check GEMINI_MODEL_* (scripts/list_gemini_models.py lists the models of your key).")
NON_ANSWER_PREFIXES = ("System ", "⚠️", "❌")


def ollama_url():
    """Local Ollama endpoint from settings/env (Q9); default http://localhost:11434."""
    return getattr(django_settings, 'OLLAMA_HOST', None) or "http://localhost:11434"


def ensure_embed_model():
    """Install the shared embedding model into LlamaIndex Settings once per process."""
    global _embed_model_loaded
    if not _embed_model_loaded:
        Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
        _embed_model_loaded = True


# Probe the configured local Ollama endpoint with a short timeout so offline
# hardware does not stall normal cloud-backed requests.
def is_local_ai_ready(timeout=3.0):
    try:
        response = requests.get(f"{ollama_url()}/api/tags", timeout=timeout)
        if response.status_code == 429:
            logger.warning("Local LLM probe rate-limited: HTTP 429.")
        elif response.status_code != 200:
            logger.warning("Local LLM probe failed: HTTP %s.", response.status_code)
        return response.status_code == 200
    except requests.exceptions.RequestException as error:
        logger.warning("Local LLM probe failed: %s.", type(error).__name__)
        return False


def reset_chat_engine(user_id=None):
    """Invalidate one user's cached state (B-08: only that user), or everything."""
    if user_id:
        _user_chat_engines.pop(user_id, None)
        _user_indexes.pop(user_id, None)
        _user_llms.pop(user_id, None)
    else:
        _user_chat_engines.clear()
        _user_indexes.clear()
        _user_llms.clear()


def get_user_paths(user):
    """Filesystem and Chroma collection locations derived from the user ID."""
    user_folder = f"user_{user.id}"
    return {
        "notes_dir": os.path.join(BASE_DIR, 'obsidian_data', user_folder),
        "collection_name": f"collection_user_{user.id}"
    }


# --- conversation memory & token budget --------------------------------------

def estimate_tokens(text):
    """Cheap token estimate (~4 characters per token); good enough for budgeting."""
    return len(text or "") // 4 + 1


def is_answer_text(text):
    return bool(text) and not str(text).startswith(NON_ANSWER_PREFIXES)


def load_chat_history(user, limit=None):
    """Last `limit` stored messages of THIS user, oldest first, as (role, text).

    System notices/errors are skipped, and the list never starts with an AI
    turn, so the model always sees a user → assistant → … sequence.
    """
    from .models import ChatMessage
    if limit is None:
        limit = getattr(django_settings, 'CHAT_HISTORY_MESSAGES', 6)
    if limit <= 0:
        return []
    rows = ChatMessage.objects.filter(user=user).order_by('-created_at', '-id')[:limit]
    history = [(m.role, m.content) for m in reversed(list(rows)) if is_answer_text(m.content)]
    while history and history[0][0] != 'user':
        history.pop(0)
    return history


def _truncate_to_tokens(text, tokens):
    return text[:max(0, tokens) * 4]


def build_messages(system_prompt, chunks, history, query, budget, inline_system=False):
    """Assemble the LLM messages within `budget` tokens.

    Note chunks get up to ~70 % of what is left after the system prompt and the
    question; the newest history messages fill the rest (older ones are dropped).
    inline_system glues the system prompt into the first user message, for
    models without system-instruction support (Gemma, see DECISIONS).
    Returns (messages, used_chunks, used_history).
    """
    fixed = estimate_tokens(system_prompt) + estimate_tokens(query) + 50
    remaining = max(0, budget - fixed)
    chunk_budget = int(remaining * 0.7)
    context_parts, used = [], 0
    for chunk in chunks:
        cost = estimate_tokens(chunk)
        if used + cost > chunk_budget:
            if not context_parts and chunk_budget > 100:
                # A single oversized chunk is cut instead of dropping all context.
                context_parts.append(_truncate_to_tokens(chunk, chunk_budget - 10))
                used = chunk_budget
            break
        context_parts.append(chunk)
        used += cost

    history_budget = remaining - used
    kept = []
    for role, text in reversed(history):
        cost = estimate_tokens(text) + 4
        if cost > history_budget:
            break
        kept.insert(0, (role, text))
        history_budget -= cost
    while kept and kept[0][0] != 'user':
        kept.pop(0)

    context = "\n\n---\n\n".join(context_parts) if context_parts else "(no matching notes were found)"
    system_text = (f"{system_prompt}\n\nContext information from the user's notes is below.\n"
                   f"---------------------\n{context}\n---------------------")

    messages = []
    if not inline_system:
        messages.append(LLMMessage(role=MessageRole.SYSTEM, content=system_text))
    for role, text in kept:
        messages.append(LLMMessage(role=MessageRole.USER if role == 'user' else MessageRole.ASSISTANT,
                                   content=text))
    messages.append(LLMMessage(role=MessageRole.USER, content=query))
    if inline_system:
        first = messages[0]
        first.content = f"{system_text}\n\n{first.content}"
    return messages, context_parts, kept


# --- providers ------------------------------------------------------------------

class _Session:
    """Per-user state created on first use (sync + index), reused until reset."""

    def __init__(self, is_local, sync_ok, vectors):
        self._is_local_engine = is_local
        self.sync_ok = sync_ok
        self.vectors = vectors


def _get_llm(user_id, provider, model, temperature):
    cache = _user_llms.setdefault(user_id, {})
    key = (provider, model)
    if key not in cache:
        if provider == 'ollama':
            logger.info("Local LLM ready: engine=Ollama, model=%s.", model)
            cache[key] = Ollama(model=model, base_url=ollama_url(), temperature=temperature,
                                request_timeout=600.0)
        else:
            info = ai_models.model_info(model)
            logger.info("Cloud LLM ready: engine=Gemini, model=%s.", model)
            cache[key] = GoogleGenAI(
                model=model,
                api_key=os.getenv("GEMINI_API_KEY"),
                temperature=temperature,
                max_tokens=ai_models.MAX_OUTPUT_TOKENS,
                context_window=info['context'],
                # No internal retries: a 429 goes straight to the next model.
                max_retries=0,
            )
    return cache[key]


def classify_llm_error(error):
    """'quota' (429/RESOURCE_EXHAUSTED), 'unavailable' (404/503 model) or None (real error)."""
    code = getattr(error, 'code', None) or getattr(error, 'status_code', None)
    text = f"{type(error).__name__} {error}".upper()
    if code == 429 or '429' in text or 'RESOURCE_EXHAUSTED' in text or 'QUOTA' in text or 'RATE LIMIT' in text:
        return 'quota'
    if code in (404, 503) or 'NOT_FOUND' in text or 'UNAVAILABLE' in text or ' 503' in text or ' 404' in text:
        return 'unavailable'
    return None


def _record_model(user_settings, label):
    """Remember which model answered (shown on Home/Settings, no extra API calls)."""
    try:
        user_settings.last_model_used = label[:100]
        user_settings.last_model_at = timezone.now()
        user_settings.save(update_fields=['last_model_used', 'last_model_at'])
    except Exception as error:  # the answer matters more than the indicator
        logger.warning("Could not store last model: %s.", type(error).__name__)


def _open_index(paths, sync_success):
    """Open (or build) the user's Chroma-backed index. Returns (index, vector_count)."""
    db = chromadb.PersistentClient(path=DB_DIR)
    chroma_collection = db.get_or_create_collection(paths["collection_name"])
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    if chroma_collection.count() == 0:
        logger.info("Vector collection empty; building initial index.")
        documents = []
        if sync_success and os.path.exists(paths["notes_dir"]):
            documents = SimpleDirectoryReader(paths["notes_dir"], required_exts=[".md"], recursive=True).load_data()
        if documents:
            index = VectorStoreIndex.from_documents(documents, storage_context=storage_context)
            logger.info("Vector index created: documents=%s.", len(documents))
        else:
            index = VectorStoreIndex.from_vector_store(vector_store)
    else:
        logger.info("Vector collection loaded: vectors=%s.", chroma_collection.count())
        index = VectorStoreIndex.from_vector_store(vector_store)
        # Smart sync: refresh_ref_docs re-embeds only new or changed documents.
        if sync_success and os.path.exists(paths["notes_dir"]):
            documents = SimpleDirectoryReader(paths["notes_dir"], required_exts=[".md"], recursive=True).load_data()
            refreshed = index.refresh_ref_docs(documents)
            logger.info("Vector index refreshed: updated=%s.", sum(refreshed))
    return index, chroma_collection.count()


def _retrieve_chunks(index, query, selected_files, top_k):
    """Top-k note chunks; selected files narrow the search, none = whole vault."""
    options = {}
    if selected_files:
        file_names = [
            name if name.lower().endswith(".md") else f"{name}.md"
            for name in selected_files
        ]
        options["filters"] = MetadataFilters(
            filters=[ExactMatchFilter(key="file_name", value=name) for name in file_names],
            condition=FilterCondition.OR,
        )
    nodes = index.as_retriever(similarity_top_k=top_k, **options).retrieve(query)
    return [node.get_content() for node in nodes]


def _budget_for(provider, model):
    if provider == 'ollama':
        return getattr(django_settings, 'PROMPT_TOKEN_BUDGET_LOCAL', 6000)
    if ai_models.is_gemma(model):
        return getattr(django_settings, 'PROMPT_TOKEN_BUDGET_GEMMA', 8000)
    return getattr(django_settings, 'PROMPT_TOKEN_BUDGET_GEMINI', 30000)


def ask_second_brain(user_query, user, selected_files=None, history=None, smart=False):
    """Run the retrieval-augmented pipeline for one user and return the answer text.

    history: previous (role, text) turns of this user (see load_chat_history);
    smart: use GEMINI_MODEL_SMART as the first cloud model (status report,
    "Smart answer" toggle). Errors are returned as "System …" texts.
    """
    selected_files = selected_files or []
    history = history or []

    from .models import get_user_settings
    user_settings = get_user_settings(user)
    paths = get_user_paths(user)
    ai_strategy = user_settings.ai_strategy or 'auto'
    try:
        temp = float(user_settings.temperature)
    except (TypeError, ValueError):
        temp = 0.7

    logger.info("Chat request received.")

    if not user_settings.github_repo_url:
        return MSG_NO_REPO

    try:
        local_online = is_local_ai_ready()
        if ai_strategy == 'local_only' and not local_online:
            logger.warning("Strict-local request rejected: local LLM is offline.")
            return MSG_LOCAL_OFFLINE

        use_local_ai = ai_strategy == 'local_only' or (ai_strategy == 'auto' and local_online)
        logger.info("LLM strategy selected: %s.", "Ollama" if use_local_ai else "Gemini")
        ensure_embed_model()

        # The cached session belongs to one provider mode; a change (PC went
        # on/offline, strategy changed) re-syncs and reopens the index.
        session = _user_chat_engines.get(user.id)
        if session is not None and session._is_local_engine != use_local_ai:
            logger.info("LLM provider changed; resetting cached engine.")
            reset_chat_engine(user.id)
            session = None

        if session is None:
            sync_success = sync_obsidian_repo(user_settings.github_repo_url, user_settings.github_token,
                                              paths["notes_dir"])
            index, vectors = _open_index(paths, sync_success)
            _user_indexes[user.id] = index
            session = _Session(use_local_ai, sync_success, vectors)
            _user_chat_engines[user.id] = session

        # Q14: explain an empty index instead of LlamaIndex's "Empty Response".
        # The empty session is not kept: the next message syncs again (the
        # network or the repository may have been fixed in the meantime).
        if session.vectors == 0:
            reset_chat_engine(user.id)
            return MSG_SYNC_FAILED if not session.sync_ok else MSG_INDEX_EMPTY

        if use_local_ai:
            candidates = [('ollama', django_settings.OLLAMA_MODEL)]
        else:
            candidates = [('gemini', model) for model in ai_models.gemini_chain(smart=smart)]
        chunks = _retrieve_chunks(_user_indexes[user.id], user_query, selected_files, SIMILARITY_TOP_K)

        display_name = user_settings.display_name or user.username
        system_prompt = (
            f"You are the secure personal AI Assistant of {display_name}. "
            "Answer questions ONLY based on the provided personal notes context "
            "and the previous messages of this conversation."
        )

        def attempt(provider, model):
            gemma = provider == 'gemini' and ai_models.is_gemma(model)
            # Gemma (16K TPM) gets a smaller similarity_top_k and an ~8K budget.
            usable = chunks[:SIMILARITY_TOP_K_GEMMA] if gemma else chunks
            messages, used_chunks, used_history = build_messages(
                system_prompt, usable, history, user_query, _budget_for(provider, model), inline_system=gemma)
            llm = _get_llm(user.id, provider, model, temp)
            started = time.monotonic()
            reply = llm.chat(messages)
            label = ai_models.ollama_label() if provider == 'ollama' else ai_models.model_info(model)['name']
            logger.info("LLM answered: provider=%s, model=%s, chunks=%s, history=%s, seconds=%.1f.",
                        provider, model, len(used_chunks), len(used_history), time.monotonic() - started)
            _record_model(user_settings, label)
            return str(reply.message.content or "")

        failures = []
        for provider, model in candidates:
            try:
                return attempt(provider, model)
            except Exception as error:
                kind = classify_llm_error(error) if provider == 'gemini' else None
                if kind is None:
                    raise
                failures.append(kind)
                logger.warning("Gemini model %s failed (%s: %s); trying the next model.",
                               model, kind, type(error).__name__)

        # Every cloud model failed with quota/unavailable errors.
        if ai_strategy == 'auto':
            logger.warning("All Gemini models exhausted; falling back to local Ollama.")
            try:
                return attempt('ollama', django_settings.OLLAMA_MODEL)
            except Exception as error:
                logger.warning("Ollama fallback failed: %s.", type(error).__name__)
        return MSG_QUOTA if 'quota' in failures else MSG_MODELS_UNAVAILABLE

    except Exception as e:
        logger.error("RAG request failed: %s.", type(e).__name__)
        return f"System Error: {str(e)}"
