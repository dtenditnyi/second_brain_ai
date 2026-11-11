"""Settings for the automated test-suite (pytest / pytest-django).

* SQLite in-memory test database (Django creates and destroys it).
* Log handlers write nowhere, so the tracked files in logs/ are not modified.
* Fast password hashing.
"""
import os as _os

# Development/test settings may use the insecure default SECRET_KEY (checked in settings.py).
_os.environ.setdefault('SECONDBRAIN_DEV_SETTINGS', '1')

from .settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'null': {'class': 'logging.NullHandler'}},
    'root': {'handlers': ['null'], 'level': 'WARNING'},
    'loggers': {
        'core.rag_engine': {'handlers': ['null'], 'propagate': False},
        'core.git_sync': {'handlers': ['null'], 'propagate': False},
        'core.views.api': {'handlers': ['null'], 'propagate': False},
    },
}

PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

# Tests run over plain http with DEBUG=False: no HTTPS redirect / secure-only cookies.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0
