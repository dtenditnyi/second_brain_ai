# RAG and hybrid inference orchestration for the Second Brain application.
# This module synchronizes each user's Markdown vault, maintains a per-user
# Chroma-backed vector index, applies optional filename filters, and routes
# generation to either the user's local Ollama service or Google Gemini.
# Django views call ask_second_brain(); Git operations are delegated to
# git_sync.py, while LlamaIndex connects embeddings, retrieval, and chat.
import os
import requests
import logging
import chromadb
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, StorageContext, Settings
from llama_index.core.vector_stores.types import ExactMatchFilter, FilterCondition, MetadataFilters
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.llms.ollama import Ollama
from llama_index.llms.google_genai import GoogleGenAI
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from .git_sync import sync_obsidian_repo

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_DIR = os.path.join(BASE_DIR, 'chroma_db')

# Use the centralized Django logging configuration for the dedicated RAG log file.
logger = logging.getLogger(__name__)

# Cache user-specific chat engines and vector indexes to avoid rebuilding them
# for every message; reset_chat_engine invalidates these entries after settings change.
_user_chat_engines = {}
_user_indexes = {}
LOCAL_OLLAMA_URL = os.getenv("OLLAMA_HOST", "http://192.168.1.128:11434")

# Use the same 384-dimensional embedding model for indexing and query vectors.
# The model is loaded lazily on the first chat request (B-15): loading it at
# import time made every process start (manage.py, gunicorn workers) slow and
# required HuggingFace network access even for pages that never use the AI.
EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_embed_model_loaded = False


def ensure_embed_model():
    """Install the shared embedding model into LlamaIndex Settings once per process."""
    global _embed_model_loaded
    if not _embed_model_loaded:
        Settings.embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
        _embed_model_loaded = True

# Probe the configured local Ollama endpoint with a short timeout so offline
# hardware does not stall normal cloud-backed requests.
# Parameters: timeout is the HTTP request timeout, in seconds.
# Returns: True only when the Ollama tags endpoint responds successfully.
def is_local_ai_ready(timeout=3.0):
    try:
        response = requests.get(f"{LOCAL_OLLAMA_URL}/api/tags", timeout=timeout)
        if response.status_code == 429:
            logger.warning("Local LLM probe rate-limited: HTTP 429.")
        elif response.status_code != 200:
            logger.warning("Local LLM probe failed: HTTP %s.", response.status_code)
        return response.status_code == 200
    except requests.exceptions.RequestException as error:
        logger.warning("Local LLM probe failed: %s.", type(error).__name__)
        return False

# Invalidate one user's cached index and engine, or clear every cached entry.
# Parameters: user_id optionally identifies the account whose cache must be reset.
# Returns: None; subsequent requests rebuild the affected runtime objects.
def reset_chat_engine(user_id=None):
    global _user_chat_engines, _user_indexes
    if user_id and user_id in _user_chat_engines:
        del _user_chat_engines[user_id]
        _user_indexes.pop(user_id, None)
    else:
        _user_chat_engines.clear()
        _user_indexes.clear()

# Derive filesystem and Chroma collection locations from the authenticated user ID.
# Parameters: user is the Django User whose private vault is being accessed.
# Returns: a mapping containing that user's notes directory and collection name.
def get_user_paths(user):
    user_folder = f"user_{user.id}"
    return {
        "notes_dir": os.path.join(BASE_DIR, 'obsidian_data', user_folder),
        "collection_name": f"collection_user_{user.id}"
    }

# Run the full retrieval-augmented response pipeline for one authenticated user.
# Parameters: user_query is the prompt text; user supplies account settings and
# identity; selected_files optionally restricts retrieval to Markdown filenames.
# Returns: the generated response as text, or a user-facing/system error message.
def ask_second_brain(user_query, user, selected_files=None):
    global _user_chat_engines, _user_indexes
    selected_files = selected_files or []
    
    from .models import get_user_settings
    settings = get_user_settings(user)
    paths = get_user_paths(user)
    ai_strategy = settings.ai_strategy or 'auto'
    try:
        temp = float(settings.temperature)
    except (TypeError, ValueError):
        temp = 0.7
    
    # Log the incoming request before checking configuration or initializing services.
    logger.info("Chat request received.")
    
    if not settings.github_repo_url:
        return "System Notification: Please configure your GitHub link."

    try:
        # Detect local hardware once, then resolve the persisted strategy into a
        # concrete provider choice. Strict-local mode fails closed when offline.
        local_online = is_local_ai_ready()

        if ai_strategy == 'local_only' and not local_online:
            logger.warning("Strict-local request rejected: local LLM is offline.")
            return "System Error: Local AI is strictly selected but the PC is offline"

        use_local_ai = (
            ai_strategy == 'local_only'
            or (ai_strategy == 'auto' and local_online)
        )
        logger.info("LLM strategy selected: %s.", "Ollama" if use_local_ai else "Gemini")
        ensure_embed_model()
        
        # A cached engine is valid only for the provider mode it was created with;
        # reset it when connectivity or the configured strategy changes that mode.
        if user.id in _user_chat_engines:
            if getattr(_user_chat_engines[user.id], '_is_local_engine', False) != use_local_ai:
                logger.info("LLM provider changed; resetting cached engine.")
                reset_chat_engine(user.id)

        # First use performs repository synchronization, configures the LLM, and
        # opens or builds the user's persistent vector index.
        if user.id not in _user_chat_engines:
            sync_success = sync_obsidian_repo(settings.github_repo_url, settings.github_token, paths["notes_dir"])
            
            # Route text generation independently from the server-side embedding
            # model: Ollama serves local mode, while Gemini serves cloud mode.
            if use_local_ai:
                logger.info("Local LLM ready: engine=Ollama, model=llama3:latest.")
                Settings.llm = Ollama(
                    model="llama3:latest",
                    base_url=LOCAL_OLLAMA_URL,
                    temperature=temp,
                    request_timeout=600.0
                )
            else:
                logger.info("Cloud LLM ready: engine=Gemini, model=gemini-3.6-flash.")
                gemini_key = os.getenv("GEMINI_API_KEY")
                Settings.llm = GoogleGenAI(
                    model="gemini-3.6-flash",
                    api_key=gemini_key,
                    temperature=temp,
                )
            
            # Attach the user's isolated Chroma collection to a LlamaIndex store.
            db = chromadb.PersistentClient(path=DB_DIR)
            
            # Create the collection on first use, or reopen it on later requests.
            chroma_collection = db.get_or_create_collection(paths["collection_name"])
            vector_store = ChromaVectorStore(chroma_collection=chroma_collection)
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            
            # An empty collection requires an initial document load; a populated
            # collection can be reopened and incrementally refreshed.
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
                
                # Smart sync compares reference-document hashes with the current
                # vault contents, embedding only new or changed documents and
                # removing stale references according to LlamaIndex refresh behavior.
                if sync_success and os.path.exists(paths["notes_dir"]):
                    logger.info("Vault changes detected; refreshing vector references.")
                    documents = SimpleDirectoryReader(paths["notes_dir"], required_exts=[".md"], recursive=True).load_data()
                    
                    # refresh_ref_docs compares stored reference hashes with the
                    # synchronized files and re-embeds only changed references.
                    refreshed = index.refresh_ref_docs(documents)
                    logger.info("Vector index refreshed: updated=%s.", sum(refreshed))
                
            _user_indexes[user.id] = index

        # Translate selected UI filenames into exact metadata filters. An empty
        # selection deliberately omits filters so retrieval spans the whole vault.
        chat_engine_options = {}
        if selected_files:
            file_names = [
                file_name if file_name.lower().endswith(".md") else f"{file_name}.md"
                for file_name in selected_files
            ]
            my_filters = MetadataFilters(
                filters=[
                    ExactMatchFilter(key="file_name", value=file_name)
                    for file_name in file_names
                ],
                condition=FilterCondition.OR,
            )
            chat_engine_options["filters"] = my_filters

        # Retrieve the five most similar chunks for context; more chunks can add
        # evidence but also consume prompt tokens and may introduce noise.
        engine = _user_indexes[user.id].as_chat_engine(
            chat_mode="context",
            similarity_top_k=5,
            system_prompt=(
                f"You are the secure personal AI Assistant of {user.username}. "
                "Answer questions ONLY based on the provided personal notes context."
            ),
            **chat_engine_options,
        )
        engine._is_local_engine = use_local_ai
        _user_chat_engines[user.id] = engine
        # Pass the user's question into retrieval and generation, then normalize
        # LlamaIndex's response object to plain text for the JSON API.
        response = engine.chat(user_query)
        return str(response)
        
    except Exception as e:
        logger.error("RAG request failed: %s.", type(e).__name__)
        return f"System Error: {str(e)}"