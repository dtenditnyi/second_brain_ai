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

# Use the same embedding model for indexing and query vectors; loaded lazily (B-15).
# B-75: the notes are mostly Russian — the old English-only bge-small model made retrieval
# almost random. multilingual-e5-small (384 dims, 512 tokens) needs "query:"/"passage:" prefixes.
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME") or "intfloat/multilingual-e5-small"
EMBED_CHUNK_SIZE = int(os.getenv("EMBED_CHUNK_SIZE") or 512)
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


def _vault_documents(notes_dir):
    """Load the vault's notes for embedding: same walker as search (no .git/.obsidian/.trash, hidden
    folders or symlinks), so a committed symlink can never pull a file from outside the vault into AI answers."""
    from pathlib import Path
    from .notes_service import _walk_md
    files = [str(full) for rel, full in _walk_md(Path(notes_dir)) if not any(p.startswith(".") for p in rel.split("/"))]
    return SimpleDirectoryReader(input_files=files).load_data() if files else []


def ollama_url():
    """Local Ollama endpoint from settings/env (Q9); default http://localhost:11434."""
    return getattr(django_settings, 'OLLAMA_HOST', None) or "http://localhost:11434"


def ensure_embed_model():
    """Install the shared embedding model into LlamaIndex Settings once per process."""
    global _embed_model_loaded
    if not _embed_model_loaded:
        extra = ({"query_instruction": "query: ", "text_instruction": "passage: "}
                 if "e5" in EMBED_MODEL_NAME.lower() else {})
        try:
            Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME, **extra)
        except TypeError:                    # older llama-index without instruction arguments
            Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
        Settings.chunk_size = EMBED_CHUNK_SIZE
        Settings.chunk_overlap = 64
        _embed_model_loaded = True


def _collection(db, name):
    """The user's Chroma collection for the CURRENT embedding model. Vectors made by another
    model are useless for search, so such a collection is dropped and rebuilt (B-75)."""
    try:
        col = db.get_collection(name)
    except Exception:
        col = None
    if col is not None and (col.metadata or {}).get("embed_model") != EMBED_MODEL_NAME:
        logger.info("Embedding model changed (%s); rebuilding the vector collection.", EMBED_MODEL_NAME)
        db.delete_collection(name)
        col = None
    if col is None:
        col = db.create_collection(name, metadata={"embed_model": EMBED_MODEL_NAME})
    return col


def _note_title(path):
    from pathlib import PurePath
    return PurePath(str(path or "note")).stem


def _selected_notes(notes_dir, selected_files, sources=None):
    """Notes the user picked go to the model WHOLE (the token budget trims them), not as the
    top-5 similar chunks: asking about one chosen note must see all of it (B-75)."""
    import unicodedata
    from pathlib import Path
    from .notes_service import _walk_md
    norm = lambda s: unicodedata.normalize("NFC", _note_title(s)).strip().lower()
    wanted = {norm(name) for name in selected_files if name}
    found = []
    if not wanted or not os.path.isdir(notes_dir):
        return found
    for rel, full in _walk_md(Path(notes_dir)):
        if norm(rel) not in wanted or full.is_symlink():
            continue
        try:
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found.append(f"Заметка «{_note_title(rel)}»:\n{text}")
        if sources is not None and str(full) not in sources:
            sources.append(str(full))
    return found


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


# get_user_paths lives in core.paths (light module, B-38); re-exported here.
from .paths import get_user_paths  # noqa: E402,F401


# --- conversation memory & token budget --------------------------------------

def estimate_tokens(text):
    """Cheap, deliberately pessimistic token estimate.

    ~4 characters per token for ASCII (English, code), ~2 for other scripts:
    Cyrillic needs about 2-3 characters per token, so a 4-chars rule would let
    a Russian prompt be twice the budget (Gemma: 16K tokens/minute).
    """
    text = text or ""
    non_ascii = sum(1 for ch in text if ord(ch) > 127)
    return (len(text) - non_ascii) // 4 + non_ascii // 2 + 1


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
    if code in (404, 500, 503, 504) or any(marker in text for marker in (
            'NOT_FOUND', 'UNAVAILABLE', 'INTERNAL', 'DEADLINE_EXCEEDED', ' 500', ' 503', ' 504', ' 404')):
        return 'unavailable'
    if isinstance(error, (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ConnectionError, TimeoutError)) \
            or type(error).__name__ in ('ConnectError', 'ReadTimeout', 'ConnectTimeout', 'RemoteProtocolError'):
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
    chroma_collection = _collection(db, paths["collection_name"])
    vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
    storage_context = StorageContext.from_defaults(vector_store=vector_store)

    if chroma_collection.count() == 0:
        logger.info("Vector collection empty; building initial index.")
        documents = []
        if sync_success and os.path.exists(paths["notes_dir"]):
            documents = _vault_documents(paths["notes_dir"])
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
            documents = _vault_documents(paths["notes_dir"])
            refreshed = index.refresh_ref_docs(documents)
            logger.info("Vector index refreshed: updated=%s.", sum(refreshed))
    return index, chroma_collection.count()


def _retrieve_chunks(index, query, selected_files, top_k, sources=None):
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
    if sources is not None:            # REST API /ask lists the notes behind the answer
        for node in nodes:
            path = str((node.metadata or {}).get("file_path") or "")
            if path and path not in sources:
                sources.append(path)
    # The note title goes with every chunk: the model can name its sources (B-75).
    return [f"Заметка «{_note_title((node.metadata or {}).get('file_name'))}»:\n{node.get_content()}"
            for node in nodes]


def _budget_for(provider, model):
    if provider == 'ollama':
        return getattr(django_settings, 'PROMPT_TOKEN_BUDGET_LOCAL', 6000)
    if ai_models.is_gemma(model):
        return getattr(django_settings, 'PROMPT_TOKEN_BUDGET_GEMMA', 8000)
    return getattr(django_settings, 'PROMPT_TOKEN_BUDGET_GEMINI', 30000)


def ask_second_brain(user_query, user, selected_files=None, history=None, smart=False, provider=None, sources=None):
    """Run the retrieval-augmented pipeline for one user and return the answer text.

    history: previous (role, text) turns of this user (see load_chat_history);
    smart: use GEMINI_MODEL_SMART as the first cloud model (status report,
    "Smart answer" toggle). Errors are returned as "System …" texts.
    provider: 'gemini' | 'claude' | 'ollama' overrides the Settings choice (REST API /ask);
    sources: optional list filled with the absolute paths of the retrieved notes.
    """
    selected_files = selected_files or []
    history = history or []

    from .models import get_user_settings
    user_settings = get_user_settings(user)
    paths = get_user_paths(user)
    ai_strategy = user_settings.ai_strategy or 'auto'
    cloud_choice = user_settings.cloud_provider or 'gemini'
    if provider == 'ollama':
        ai_strategy = 'local_only'
    elif provider in ('gemini', 'claude'):
        ai_strategy, cloud_choice = 'cloud_only', provider
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
            # Claude (Round 4 / G-E1) first when chosen in Settings; Gemini stays the fallback.
            from . import ai_providers
            if cloud_choice == 'claude' and ai_providers.claude_available():
                candidates.insert(0, ('claude', ai_providers.ClaudeProvider(user_settings.claude_model).model))
        chunks = _selected_notes(paths["notes_dir"], selected_files, sources) if selected_files else []
        if not chunks:
            chunks = _retrieve_chunks(_user_indexes[user.id], user_query, selected_files, SIMILARITY_TOP_K, sources)

        display_name = user_settings.display_name or user.username
        system_prompt = (
            f"You are the secure personal AI Assistant of {display_name}, working with their Obsidian notes. "
            "Answer questions ONLY based on the provided personal notes context "
            "and the previous messages of this conversation. "
            "The context below IS the user's notes: never say that you have no access to them. "
            "If the notes answer the question only partly, say what they do contain and name the notes "
            "(titles in «»). If nothing relevant is there, say so in one sentence. "
            "Always answer in the language of the user's question (usually Russian)."
        )

        def attempt(provider, model):
            gemma = provider == 'gemini' and ai_models.is_gemma(model)
            # Gemma (16K TPM) gets a smaller similarity_top_k and an ~8K budget.
            usable = chunks[:SIMILARITY_TOP_K_GEMMA] if gemma else chunks
            messages, used_chunks, used_history = build_messages(
                system_prompt, usable, history, user_query, _budget_for(provider, model), inline_system=gemma)
            started = time.monotonic()
            if provider == 'claude':
                from . import ai_providers
                claude = ai_providers.ClaudeProvider(model)
                answer = claude.chat(messages[0].content, [
                    {"role": "user" if m.role == MessageRole.USER else "assistant", "content": m.content}
                    for m in messages[1:]]).text
                logger.info("LLM answered: provider=claude, model=%s, chunks=%s, history=%s, seconds=%.1f.",
                            model, len(used_chunks), len(used_history), time.monotonic() - started)
                _record_model(user_settings, claude.label)
                return answer
            llm = _get_llm(user.id, provider, model, temp)
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
                if provider == 'claude':
                    kind = getattr(error, 'kind', None)
                    kind = kind if kind in ('quota', 'unavailable') else None
                else:
                    kind = classify_llm_error(error) if provider == 'gemini' else None
                if kind is None:
                    raise
                failures.append(kind)
                logger.warning("Cloud model %s failed (%s: %s); trying the next model.",
                               model, kind, type(error).__name__)

        # Every cloud model failed with quota/unavailable errors.
        if ai_strategy == 'auto':
            # The probe said "offline" a moment ago; ask again quickly instead of
            # letting a 600 s Ollama timeout hang an unreachable OLLAMA_HOST.
            if is_local_ai_ready(timeout=2.0):
                logger.warning("All Gemini models exhausted; falling back to local Ollama.")
                try:
                    return attempt('ollama', django_settings.OLLAMA_MODEL)
                except Exception as error:
                    logger.warning("Ollama fallback failed: %s.", type(error).__name__)
            else:
                logger.warning("All Gemini models exhausted and local Ollama is offline.")
        return MSG_QUOTA if 'quota' in failures else MSG_MODELS_UNAVAILABLE

    except Exception as e:
        logger.error("RAG request failed: %s.", type(e).__name__)
        return f"System Error: {str(e)}"


def reindex_notes(user, changed=(), removed=()):
    """Re-index only these vault notes in the user's Chroma collection (Round 4 / G-D5).

    ``changed``/``removed`` are vault-relative paths. Vectors of every listed note are
    deleted (matched by file name + path metadata), then changed notes that still exist
    are read and inserted again. Used after edits made by the site, the agent or the API.
    """
    from pathlib import Path
    paths = get_user_paths(user)
    root = Path(paths["notes_dir"])
    targets = [p for p in list(changed) + list(removed) if str(p).lower().endswith(".md")]
    if not targets:
        return 0
    ensure_embed_model()
    db = chromadb.PersistentClient(path=DB_DIR)
    collection = _collection(db, paths["collection_name"])
    for rel in targets:
        full = (root / rel)
        for candidate in {str(full), str(full.resolve()), os.path.abspath(str(full))}:
            collection.delete(where={"file_path": candidate})
    existing = [str(root / rel) for rel in changed if (root / rel).is_file() and not (root / rel).is_symlink()]
    if existing:
        vector_store = ChromaVectorStore(chroma_collection=collection)
        index = VectorStoreIndex.from_vector_store(vector_store)
        for document in SimpleDirectoryReader(input_files=existing).load_data():
            index.insert(document)
    _user_chat_engines.pop(user.id, None)       # cached session sees the new vectors on next question
    logger.info("Re-indexed notes: changed=%s removed=%s.", len(existing), len(list(removed)))
    return len(existing)
