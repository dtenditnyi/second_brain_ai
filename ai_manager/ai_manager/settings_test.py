"""Settings for the automated test-suite (pytest / pytest-django).

* SQLite in-memory test database (Django creates and destroys it).
* Log handlers write nowhere, so the tracked files in logs/ are not modified.
* Fast password hashing.
"""
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
