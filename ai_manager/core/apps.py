"""Django application registration metadata for the core workspace app."""
from django.apps import AppConfig

class CoreConfig(AppConfig):
    # Use wide primary keys by default for newly declared application models.
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # The ONE allowed-tags list (Round 4 / G-API7): settings.ALLOWED_TAGS → the pure parser.
        from django.conf import settings
        from . import tasks_md
        tasks_md.configure_allowed_tags(getattr(settings, 'ALLOWED_TAGS', None))
