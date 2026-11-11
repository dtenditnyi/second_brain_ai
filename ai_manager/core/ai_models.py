"""Single source of truth for the Gemini/Ollama models shown in the UI and used by the code.

Model IDs come from Django settings (env with defaults, see settings.py); this
module adds human-readable names and the free-tier limits that the owner
measured for their key on 2026-11-10 (RPM / TPM / RPD). Unknown IDs (e.g. a
custom GEMINI_MODEL_DEFAULT) still work: their label is the raw ID.
"""
from django.conf import settings

# id -> display name, requests/minute, tokens/minute, requests/day, context window
MODEL_CATALOGUE = {
    'gemini-3.8-flash': {'name': 'Gemini 3.8 Flash', 'rpm': 5, 'tpm': 250_000, 'rpd': 20, 'context': 1_048_576},
    'gemini-3.6-flash': {'name': 'Gemini 3.6 Flash', 'rpm': 5, 'tpm': 250_000, 'rpd': 20, 'context': 1_048_576},
    'gemini-3-flash': {'name': 'Gemini 3 Flash', 'rpm': 5, 'tpm': 250_000, 'rpd': 20, 'context': 1_048_576},
    'gemini-2.5-flash': {'name': 'Gemini 2.5 Flash', 'rpm': 5, 'tpm': 250_000, 'rpd': 20, 'context': 1_048_576},
    'gemini-3.5-flash-lite': {'name': 'Gemini 3.5 Flash Lite', 'rpm': 15, 'tpm': 250_000, 'rpd': 500, 'context': 1_048_576},
    'gemini-3.1-flash-lite': {'name': 'Gemini 3.1 Flash Lite', 'rpm': 15, 'tpm': 250_000, 'rpd': 500, 'context': 1_048_576},
    'gemma-4-31b-it': {'name': 'Gemma 4 31B', 'rpm': 30, 'tpm': 16_000, 'rpd': 14_400, 'context': 128_000},
    'gemma-4-26b-a4b-it': {'name': 'Gemma 4 26B', 'rpm': 30, 'tpm': 16_000, 'rpd': 14_400, 'context': 128_000},
}
DEFAULT_CONTEXT_WINDOW = 128_000
# Upper bound for one answer; passing it (with context_window) also stops the
# LlamaIndex wrapper from calling models.get() on every construction.
MAX_OUTPUT_TOKENS = 2048


def is_gemma(model_id):
    return 'gemma' in (model_id or '').lower()


def model_info(model_id):
    info = dict(MODEL_CATALOGUE.get(model_id, {}))
    info.setdefault('name', model_id)
    info.setdefault('rpd', None)
    info.setdefault('context', DEFAULT_CONTEXT_WINDOW)
    info['id'] = model_id
    info['is_gemma'] = is_gemma(model_id)
    return info


def model_label(model_id):
    """'Gemini 3.5 Flash Lite (~500/day)' — the daily limit only when known."""
    info = model_info(model_id)
    if info['rpd']:
        return f"{info['name']} (~{info['rpd']:,}/day)".replace(',', ' ')
    return info['name']


def gemini_chain(smart=False):
    """Models to try in order: primary (DEFAULT or SMART), then the fallbacks, no duplicates."""
    primary = settings.GEMINI_MODEL_SMART if smart else settings.GEMINI_MODEL_DEFAULT
    chain = []
    for model_id in [primary, *settings.GEMINI_FALLBACK_MODELS]:
        if model_id and model_id not in chain:
            chain.append(model_id)
    return chain


def ollama_label():
    return f"Ollama {settings.OLLAMA_MODEL} (local)"


def ui_model_config():
    """Context for templates: what the dropdown and the info box show."""
    return {
        'default': model_info(settings.GEMINI_MODEL_DEFAULT),
        'default_label': model_label(settings.GEMINI_MODEL_DEFAULT),
        'smart': model_info(settings.GEMINI_MODEL_SMART),
        'smart_label': model_label(settings.GEMINI_MODEL_SMART),
        'fallbacks': [model_label(m) for m in settings.GEMINI_FALLBACK_MODELS],
        'ollama_label': ollama_label(),
    }
