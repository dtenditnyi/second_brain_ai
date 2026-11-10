"""Shared view helpers for exposing authenticated settings to templates."""
from ..models import get_user_settings
# Return the related settings model for signed-in users and a safe display-only
# fallback mapping for anonymous contexts.
# Parameters: user is the Django request user supplied by the calling view.
# Returns: UserSettings for authenticated accounts, otherwise guest defaults.
def get_user_config(user):
    if user.is_authenticated:
        return get_user_settings(user)
    return {
        "display_name": "Guest Traveler",
        "email": "",
        "theme": "cyberpunk",
        "accent_color": "cyan",
        "ai_strategy": "auto",
        "temperature": "0.7"
    }