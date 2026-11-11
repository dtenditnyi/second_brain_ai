"""Authenticated page controllers that assemble template context for the UI."""
import os
from datetime import datetime
from collections import Counter
from django.conf import settings as django_settings
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils.timezone import make_aware

from ..models import Task, ChatMessage, get_user_settings
from .. import rag_engine
from .. import ai_models, ai_providers
from .. import tasks_service
from .utils import get_user_config

@login_required(login_url='login')
def home_view(request):
    # Build the dashboard from the current user's tasks, note files, and preferences.
    # The context is consumed by home.html and its home.js/tasks.js interactions.
    from ..paths import get_user_paths
    tasks_state = _sync_tasks_quietly(request.user)
    tasks = Task.objects.filter(user=request.user).exclude(status__in=('cancelled', 'forwarded'))
    
    top_focus = "General Systems"
    active_tags = tasks.exclude(status='done').exclude(tags__exact='').values_list('tags', flat=True)
    # Use the most common active task tag as a lightweight dashboard focus signal.
    if active_tags:
        all_tags = [tag.strip() for tags_str in active_tags for tag in tags_str.split(',')]
        if all_tags:
            top_focus = Counter(all_tags).most_common(1)[0][0]

    paths = get_user_paths(request.user)
    recent_notes = []
    
    # Derive recent notes from filesystem metadata without reading note bodies.
    if os.path.exists(paths["notes_dir"]):
        for root, dirs, files in os.walk(paths["notes_dir"]):
            for file in files:
                if file.endswith(".md"):
                    file_path = os.path.join(root, file)
                    mtime = os.path.getmtime(file_path)
                    dt_mtime = make_aware(datetime.fromtimestamp(mtime))
                    recent_notes.append({'name': file.replace('.md', ''), 'modified_at': dt_mtime})
                    
    recent_notes.sort(key=lambda x: x['modified_at'], reverse=True)
    top_recent_notes = recent_notes[:3]

    context = {
        'active_page': 'home', 
        'config': get_user_config(request.user),
        'todo_tasks': tasks.filter(status='todo'),
        'progress_tasks': tasks.filter(status='in_progress'),
        'done_tasks': tasks.filter(status='done'),
        'recent_tasks': tasks.order_by('-created_at')[:4],
        'recent_notes': top_recent_notes,
        'total_notes_count': len(recent_notes),
        'top_focus': top_focus,
        'models': ai_models.ui_model_config(),
        'tasks_state': tasks_state,
    }
    return render(request, 'home.html', context)

@login_required(login_url='login')
def ai_chat_view(request):
    # Assemble all vault filenames for the context picker and the latest chat turns.
    # The template uses all_files for selection and context_files for initial state.
    from ..paths import get_user_paths
    paths = get_user_paths(request.user)
    synced_notes = []
    if os.path.exists(paths["notes_dir"]):
        for root, dirs, files in os.walk(paths["notes_dir"]):
            for file in files:
                if file.endswith(".md"):
                    synced_notes.append(file.replace(".md", ""))
                    
    # A list (not a reversed() iterator, which is always truthy) so the template's
    # `{% if not chat_history %}` greeting works (B-05).
    chat_history = list(reversed(ChatMessage.objects.filter(user=request.user).order_by('-created_at')[:50]))
    synced_notes.sort()
    context = {
        'active_page': 'ai-chat', 
        'config': get_user_config(request.user),
        # Q12: nothing is preselected — without a selection the whole vault is searched.
        'all_files': synced_notes,
        'models': ai_models.ui_model_config(),
        'chat_history': chat_history
    }
    return render(request, 'ai-chat.html', context)

@login_required(login_url='login')
def notes_view(request):
    # Synchronize a configured repository when no local clone exists, then expose
    # the user's note names to the file explorer template.
    import os
    from ..paths import get_user_paths
    from ..git_sync import sync_obsidian_repo
    
    paths = get_user_paths(request.user)
    settings = get_user_settings(request.user)
    git_folder = os.path.join(paths["notes_dir"], '.git')
    
    if settings.github_repo_url and not os.path.exists(git_folder):
        sync_obsidian_repo(settings.github_repo_url, settings.github_token, paths["notes_dir"])

    # Round 4: each entry carries its vault-relative path (the editor works by path).
    entries = []
    if os.path.exists(paths["notes_dir"]):
        for root, dirs, files in os.walk(paths["notes_dir"]):
            dirs[:] = sorted(d for d in dirs if d not in (".git", ".obsidian", ".trash"))
            for file in sorted(files):
                if file.endswith(".md"):
                    rel = os.path.relpath(os.path.join(root, file), paths["notes_dir"]).replace(os.sep, "/")
                    entries.append({"name": file[:-3], "path": rel})

    return render(request, 'notes.html', {
        'active_page': 'notes',
        'config': get_user_config(request.user),
        'user_notes': [e["name"] for e in entries],
        'note_entries': entries,
        'vault_editable': bool(settings.github_repo_url),
    })

@login_required(login_url='login')
def tasks_view(request):
    # Separate outstanding and recently completed work for the task board template.
    tasks_state = _sync_tasks_quietly(request.user)
    tasks = Task.objects.filter(user=request.user)
    return render(request, 'tasks.html', {
        'active_page': 'tasks',
        'config': get_user_config(request.user),
        'active_tasks': tasks.exclude(status__in=('done', 'cancelled', 'forwarded')).order_by('due_date', 'position'),
        'completed_tasks': tasks.filter(status__in=('done', 'cancelled', 'forwarded')).order_by('-created_at')[:10],
        'tasks_state': tasks_state,
        'allowed_tags': tasks_service.tasks_md.ALLOWED_TAGS,
    })


def _sync_tasks_quietly(user):
    """Sync the tasks note when stale; returns what the page shows about it (Round 3 / G-C4)."""
    try:
        result = tasks_service.sync_tasks(user)
    except Exception as error:  # a page must never fail because of the vault
        import logging
        logging.getLogger('core.tasks').error('Task sync failed: %s', type(error).__name__)
        result = {'status': 'error'}
    settings = get_user_settings(user)
    return {
        'vault': bool(settings.github_repo_url),
        'note_path': tasks_service.tasks_note_path(user),
        'last_sync': settings.tasks_last_sync,
        'error': settings.tasks_sync_error,
        'status': result.get('status'),
        'pending': Task.objects.filter(user=user, synced=False).count(),
    }


@login_required(login_url='login')
def settings_view(request):
    # Render the preferences page with the authenticated user's settings object.
    config = get_user_config(request.user)
    return render(request, 'settings.html', {
        'active_page': 'settings',
        'config': config,
        # Q7: only whether a token exists is sent to the template, never the token.
        'has_github_token': bool(config.github_token),
        'default_tasks_note_path': django_settings.TASKS_NOTE_PATH,
        'models': ai_models.ui_model_config(),
        'claude_models': ai_providers.CLAUDE_MODELS,
        'claude_available': ai_providers.claude_available(),
        'default_claude_model': django_settings.ANTHROPIC_MODEL,
    })