"""Local/audit settings: identical to production settings, but use a SQLite COPY
of the database instead of the Docker PostgreSQL service.

Usage:
    python manage.py runserver --settings=ai_manager.settings_local

The database file (audit_copy_db.sqlite3) is a copy of db.sqlite3 and is
ignored by git (*.sqlite3). The production database is never touched.
Override the path with the AUDIT_SQLITE_PATH environment variable.
"""
import os

from .settings import *  # noqa: F401,F403
from .settings import BASE_DIR

# Local development always runs with DEBUG on (production reads it from env).
DEBUG = True

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.environ.get('AUDIT_SQLITE_PATH', str(BASE_DIR / 'audit_copy_db.sqlite3')),
    }
}

# Write local logs to separate (git-ignored) files so the tracked logs/*.log
# files are not modified by local/audit runs.
import copy as _copy
from .settings import LOGGING as _BASE_LOGGING, LOGS_DIR as _LOGS_DIR

LOGGING = _copy.deepcopy(_BASE_LOGGING)
LOGGING['handlers']['rag_file']['filename'] = _LOGS_DIR / 'local_rag_engine.log'
LOGGING['handlers']['system_file']['filename'] = _LOGS_DIR / 'local_system.log'
