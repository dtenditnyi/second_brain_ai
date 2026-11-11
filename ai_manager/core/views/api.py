"""JSON endpoints connecting browser interactions to Django models and RAG services."""
import json
import logging
import os
import re
from django.db import transaction
from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from ..models import Task, ChatMessage, UserSettings, get_user_settings
from .. import rag_engine
from .. import tasks_service
from ..vault_writer import UnsafePath, safe_path
from .utils import parse_json_body

logger = logging.getLogger(__name__)


def _task_error(message):
    return JsonResponse({'status': 'error', 'msg': message}, status=400)

@login_required(login_url='login')
def api_chat_message(request):
    # Validate a chat POST, pass memory + optional file filters to RAG, persist the turns.
    # JSON: message, selected_files (empty = whole vault), smart (bool: SMART model),
    # mode ("chat" default | "report": Home status report — SMART model, no memory,
    # nothing stored in the chat history, Q3).
    # Returns: {status, reply, model} or HTTP 400 when the request is unusable.
    if request.method == "POST":
        data = parse_json_body(request)
        if data is None:
            return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
        user_message = data.get('message', '')
        if not isinstance(user_message, str):
            user_message = ''
        # Accept both current and legacy browser key spellings, then discard
        # malformed entries before the filenames reach the retrieval layer.
        selected_files = data.get('selected_files', data.get('selectedFiles', []))
        if not isinstance(selected_files, list):
            selected_files = []
        selected_files = [file_name for file_name in selected_files if isinstance(file_name, str)]
        is_report = data.get('mode') == 'report'
        smart = is_report or data.get('smart') is True

        if user_message.strip():
            # Memory is read BEFORE the new message is stored (it is the query itself).
            history = [] if is_report else rag_engine.load_chat_history(request.user)
            if not is_report:
                ChatMessage.objects.create(user=request.user, role='user', content=user_message)
            ai_response = rag_engine.ask_second_brain(
                user_message, request.user, selected_files, history=history, smart=smart)
            if not is_report:
                ChatMessage.objects.create(user=request.user, role='ai', content=ai_response)
            model = UserSettings.objects.filter(user=request.user).values_list('last_model_used', flat=True).first()
            return JsonResponse({'status': 'ok', 'reply': ai_response, 'model': model or ''})
    return JsonResponse({'status': 'error'}, status=400)

@login_required(login_url='login')
@transaction.atomic  # user + settings rows are saved together
def api_save_settings(request):
    # Persist account identity separately from per-user application preferences.
    # Parameters: request.body is JSON produced by settings.js.
    # Returns: JSON status; the RAG cache is reset so subsequent turns use new settings.
    if request.method == "POST":
        data = parse_json_body(request)
        if data is None:
            return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
        # A JSON null means "not provided" and keeps the stored value (B-03).
        def field(key, current):
            value = data.get(key)
            return current if value is None else value

        # Q6: the display name is NOT the login. A "username" key is ignored;
        # the login can only be changed by an administrator (Core Matrix).
        display_name = data.get('display_name')
        if display_name is not None:
            if not isinstance(display_name, str):
                return JsonResponse({'status': 'error', 'msg': 'Invalid value for display_name.'}, status=400)
            display_name = display_name.strip()
            if not display_name:
                return JsonResponse({'status': 'error', 'msg': 'Display name cannot be empty.'}, status=400)
            if len(display_name) > UserSettings._meta.get_field('display_name').max_length:
                return JsonResponse({'status': 'error', 'msg': 'Display name is too long (max 100 characters).'}, status=400)
        # Free-text preferences must be strings that fit their columns (Postgres enforces lengths).
        for key in ('theme', 'accent_color'):
            value = data.get(key)
            if value is not None and (not isinstance(value, str)
                                      or len(value) > UserSettings._meta.get_field(key).max_length):
                return JsonResponse({'status': 'error', 'msg': f'Invalid value for {key}.'}, status=400)
        email = str(field('email', request.user.email)).strip()
        if len(email) > User._meta.get_field('email').max_length:
            return JsonResponse({'status': 'error', 'msg': 'Email is too long.'}, status=400)

        tasks_path = data.get('tasks_note_path')
        if tasks_path is not None:
            if not isinstance(tasks_path, str) or len(tasks_path) > 300:
                return JsonResponse({'status': 'error', 'msg': 'Invalid tasks note path.'}, status=400)
            tasks_path = tasks_path.strip()
            if tasks_path:
                try:
                    import tempfile
                    safe_path(tempfile.gettempdir(), tasks_path)
                except UnsafePath as exc:
                    return JsonResponse({'status': 'error', 'msg': f'Tasks note path: {exc}'}, status=400)
                if not tasks_path.lower().endswith('.md'):
                    return JsonResponse({'status': 'error', 'msg': 'Tasks note path must end with .md'}, status=400)
        # Round 4 / G-E1: cloud provider (Gemini / Claude) and Claude model; Claude needs a key.
        from .. import ai_providers
        cloud_provider = data.get('cloud_provider')
        if cloud_provider is not None and cloud_provider not in ('gemini', 'claude'):
            return JsonResponse({'status': 'error', 'msg': 'Unknown AI provider.'}, status=400)
        if cloud_provider == 'claude' and not ai_providers.claude_available():
            return JsonResponse({'status': 'error', 'msg': 'Claude is unavailable: ANTHROPIC_API_KEY is not set on the server.'}, status=400)
        claude_model = data.get('claude_model')
        if claude_model is not None and claude_model != '' and claude_model not in ai_providers.CLAUDE_MODEL_IDS:
            return JsonResponse({'status': 'error', 'msg': 'Unknown Claude model.'}, status=400)
        auto_apply = data.get('agent_auto_apply_additions')
        if auto_apply is not None and not isinstance(auto_apply, bool):
            return JsonResponse({'status': 'error', 'msg': 'Invalid value for agent_auto_apply_additions.'}, status=400)
        new_token = data.get('github_token')
        # 255 plain characters still fit the 500-char encrypted column (B-14).
        if isinstance(new_token, str) and len(new_token.strip()) > 255:
            return JsonResponse({'status': 'error', 'msg': 'GitHub token is too long.'}, status=400)

        if email != request.user.email:
            request.user.email = email
            request.user.save(update_fields=['email'])

        settings = get_user_settings(request.user)
        
        if display_name is not None:
            settings.display_name = display_name
        settings.theme = field('theme', settings.theme)
        settings.accent_color = field('accent_color', settings.accent_color)
        ai_strategy = data.get('ai_strategy', settings.ai_strategy)
        if ai_strategy in {'auto', 'local_only', 'cloud_only'}:
            settings.ai_strategy = ai_strategy
        if cloud_provider is not None:
            settings.cloud_provider = cloud_provider
        if claude_model is not None:
            settings.claude_model = claude_model
        if auto_apply is not None:
            settings.agent_auto_apply_additions = auto_apply
        # Bound the sampling temperature to the UI's supported range and recover
        # from malformed client values without rejecting unrelated preferences.
        try:
            temperature = float(data.get('temperature', settings.temperature))
        except (TypeError, ValueError):
            temperature = 0.7
        settings.temperature = max(0.0, min(1.0, temperature))
        settings.github_repo_url = str(field('github_repo_url', settings.github_repo_url)).strip()
        if tasks_path is not None and tasks_path != settings.tasks_note_path:
            settings.tasks_note_path = tasks_path
            settings.tasks_last_sync = None          # re-read the (other) note on next visit
        # Q7: the token is never sent back to the browser. An empty/missing value
        # keeps the stored token; only an explicit clear_github_token removes it.
        if data.get('clear_github_token') is True:
            settings.github_token = ''
        else:
            new_token = data.get('github_token')
            if isinstance(new_token, str) and new_token.strip():
                settings.github_token = new_token.strip()
        settings.save()
        logger.info(
            "User settings updated: AI Strategy -> %s; Temperature -> %.1f.",
            settings.ai_strategy,
            settings.temperature,
        )
        
        rag_engine.reset_chat_engine(request.user.id)
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)

def _clean_task_fields(data, require_title):
    """Validate task fields from JSON. Returns (fields, error_response)."""
    fields = {}
    if 'title' in data or require_title:
        raw_title = data.get('title') or ''
        if not isinstance(raw_title, str):
            return None, _task_error('Title, priority and tags must be strings.')
        title = raw_title.strip()
        if not title:
            return None, _task_error('Task title is required.')
        if len(title) > Task._meta.get_field('title').max_length:
            return None, _task_error('Task title is too long.')
        fields['title'] = title
    if 'priority' in data or require_title:
        priority = data.get('priority') or 'medium'
        if not isinstance(priority, str) or priority not in dict(Task.PRIORITY_CHOICES):
            return None, _task_error('Unknown priority.' if isinstance(priority, str) else 'Title, priority and tags must be strings.')
        fields['priority'] = priority
    if 'tags' in data or require_title:
        tags = data.get('tags') or ''
        if not isinstance(tags, str):                       # B-24: lists/dicts rejected
            return None, _task_error('Title, priority and tags must be strings.')
        if len(tags) > Task._meta.get_field('tags').max_length:
            return None, _task_error('Tags are too long.')
        fields['tags'] = tags
    if 'due_date' in data or require_title:
        raw_due = data.get('due_date') or None
        due_date = None
        if raw_due:
            try:
                due_date = parse_date(str(raw_due))
            except ValueError:
                due_date = None
            if due_date is None:
                return None, _task_error('Invalid due date (expected YYYY-MM-DD).')
        fields['due_date'] = due_date
    if 'status' in data:
        status = data.get('status')
        if not isinstance(status, str) or status not in dict(Task.STATUS_CHOICES):
            return None, _task_error('Unknown task status.')
        fields['status'] = status
    return fields, None


def _sync_error_response(error):
    # 409: the vault refused or changed under us; the message is meant for the user.
    return JsonResponse({'status': 'error', 'msg': str(error)}, status=409)


@login_required(login_url='login')
def api_add_task(request):
    # Create a task. With a connected vault it is written to the tasks note (Round 3),
    # otherwise it is stored in the database only. Returns the cache row id.
    if request.method == "POST":
        data = parse_json_body(request)
        if data is None:
            return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
        fields, error = _clean_task_fields(data, require_title=True)
        if error:
            return error
        try:
            task = tasks_service.add_task(
                request.user, text=fields['title'], due=fields['due_date'].isoformat() if fields['due_date'] else None,
                priority=fields['priority'], tags=fields['tags'], status=fields.get('status'))
        except ValueError as exc:
            return _task_error(str(exc))
        except tasks_service.TaskSyncError as exc:
            return _sync_error_response(exc)
        return JsonResponse({'status': 'ok', 'task_id': task.id, 'synced': task.synced})
    return JsonResponse({'status': 'error'}, status=400)


@login_required(login_url='login')
def api_update_task_status(request):
    # Update status and/or title, due date, priority, tags of the caller's own task.
    if request.method == "POST":
        data = parse_json_body(request)
        if data is None:
            return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
        try:
            task_id = int(data.get('task_id'))
        except (TypeError, ValueError):
            if 'status' in data and (not isinstance(data.get('status'), str) or data.get('status') not in dict(Task.STATUS_CHOICES)):
                return _task_error('Unknown task status.')
            return _task_error('Invalid task id.')
        fields, error = _clean_task_fields(data, require_title=False)
        if error:
            return error
        if not fields:
            return _task_error('Unknown task status.')
        if not Task.objects.filter(id=task_id, user=request.user).exists():
            return JsonResponse({'status': 'error', 'msg': 'Task not found'}, status=404)
        try:
            task = tasks_service.update_task(request.user, task_id, **fields)
        except ValueError as exc:
            return _task_error(str(exc))
        except tasks_service.TaskSyncError as exc:
            return _sync_error_response(exc)
        return JsonResponse({'status': 'ok'})
    # Non-POST requests previously fell through and returned None → HTTP 500 (B-04).
    return JsonResponse({'status': 'error'}, status=400)


@login_required(login_url='login')
def api_delete_task(request):
    if request.method != "POST":
        return JsonResponse({'status': 'error'}, status=400)
    data = parse_json_body(request)
    if data is None:
        return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
    try:
        task_id = int(data.get('task_id'))
    except (TypeError, ValueError):
        return _task_error('Invalid task id.')
    if not Task.objects.filter(id=task_id, user=request.user).exists():
        return JsonResponse({'status': 'error', 'msg': 'Task not found'}, status=404)
    try:
        tasks_service.delete_task(request.user, task_id)
    except tasks_service.TaskSyncError as exc:
        return _sync_error_response(exc)
    return JsonResponse({'status': 'ok'})


@login_required(login_url='login')
def api_tasks_sync(request):
    # "Refresh" button: sync the tasks note now (Round 3 / G-C4).
    if request.method != "POST":
        return JsonResponse({'status': 'error'}, status=400)
    result = tasks_service.sync_tasks(request.user, force=True)
    code = 200 if result.get('status') in ('ok', 'local', 'fresh') else 503
    return JsonResponse(result, status=code)


@login_required(login_url='login')
def api_get_note_content(request):
    # Load a Markdown note, convert Obsidian wiki links, and find inbound mentions.
    # Parameters: the GET query parameter "name" identifies the requested note.
    # Returns: rendered HTML and backlink snippets, or a JSON error response.
    from ..paths import get_user_paths
    note_name = request.GET.get('name')
    note_path = request.GET.get('path')
    if not note_name and not note_path:
        return JsonResponse({'status': 'error', 'msg': 'No note name provided.'}, status=400)

    paths = get_user_paths(request.user)
    if get_user_settings(request.user).github_repo_url:
        try:                                   # first visit: clone the vault (Round 5)
            from ..notes_service import _local_root
            _local_root(request.user)
        except Exception as error:             # offline etc.: show what the local copy has
            logger.info("Vault clone skipped: %s", type(error).__name__)
    current_file_path = None
    if note_path:
        # Round 4: open by vault-relative path (validated: no escape, .md only).
        try:
            candidate = safe_path(paths["notes_dir"], note_path)
        except UnsafePath:
            candidate = None
        if candidate is not None and candidate.suffix.lower() == ".md" and candidate.is_file():
            current_file_path = str(candidate)
            note_name = candidate.stem
    else:
        target_file_name = f"{note_name}.md"
        if os.path.exists(paths["notes_dir"]):
            for root, dirs, files in os.walk(paths["notes_dir"]):
                dirs[:] = sorted(d for d in dirs if d not in (".git", ".obsidian", ".trash"))
                if target_file_name in files:
                    current_file_path = os.path.join(root, target_file_name)
                    break
    target_file_name = f"{note_name}.md"

    if not current_file_path:
        return JsonResponse({'status': 'error', 'msg': 'Note not found in the secure vault.'}, status=404)

    try:
        from .. import render as note_render, vault_index
        with open(current_file_path, 'rb') as f:
            raw_markdown = f.read().decode('utf-8', errors='replace')
        rel_path = os.path.relpath(current_file_path, paths["notes_dir"]).replace(os.sep, "/")
        # Round 5 (F2): Obsidian-like server render (callouts, checkboxes, embeds, Dataview-lite…);
        # raw HTML from the note is escaped, never executed.
        notes = vault_index.scan_root(paths["notes_dir"])
        rendered = note_render.render_note(paths["notes_dir"], rel_path, raw_markdown, notes)
        links = vault_index.mentions(request.user, rel_path, notes) or {"backlinks": [], "unlinked": []}
        backlinks = [{'title': b['name'], 'path': b['path'], 'snippet': f"...{b['snippet']}..."} for b in links['backlinks']]
        favorites = get_user_settings(request.user).favorite_notes or []
        return JsonResponse({'status': 'ok', 'html_content': rendered['html'], 'backlinks': backlinks,
                             'unlinked': links['unlinked'], 'name': note_name, 'path': rel_path,
                             'favorite': rel_path in favorites,
                             'editable': bool(get_user_settings(request.user).github_repo_url)})
    except Exception as e:
        logger.exception("Note render failed")
        return JsonResponse({'status': 'error', 'msg': f'Не удалось показать заметку: {type(e).__name__}'}, status=500)

@login_required(login_url='login')
def api_sidebar_stats(request):
    # Aggregate the current user's task completion counts for the sidebar indicator.
    # Returns: JSON with completed, total, and integer percentage values.
    total_tasks = Task.objects.filter(user=request.user).count()
    done_tasks = Task.objects.filter(user=request.user, status='done').count()
    percent = int((done_tasks / total_tasks) * 100) if total_tasks > 0 else 0
    return JsonResponse({'status': 'ok', 'percent': percent, 'done': done_tasks, 'total': total_tasks})