"""Per-user filesystem locations — a light module (no AI imports).

Used by the vault writer, task sync and pages, so that `manage.py sync_tasks`
(run by the scheduler every minute) does not import torch / llama_index (B-38).
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_user_paths(user):
    """Filesystem and Chroma collection locations derived from the user ID."""
    user_folder = f"user_{user.id}"
    return {
        "notes_dir": os.path.join(BASE_DIR, 'obsidian_data', user_folder),
        "collection_name": f"collection_user_{user.id}"
    }
