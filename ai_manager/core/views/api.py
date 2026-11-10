"""JSON endpoints connecting browser interactions to Django models and RAG services."""
import json
import logging
import os
import re
import markdown
from html import escape
from django.db import transaction
from django.http import JsonResponse
from django.utils.dateparse import parse_date
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User

from ..models import Task, ChatMessage, UserSettings, get_user_settings
from .. import rag_engine
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
        # Bound the sampling temperature to the UI's supported range and recover
        # from malformed client values without rejecting unrelated preferences.
        try:
            temperature = float(data.get('temperature', settings.temperature))
        except (TypeError, ValueError):
            temperature = 0.7
        settings.temperature = max(0.0, min(1.0, temperature))
        settings.github_repo_url = str(field('github_repo_url', settings.github_repo_url)).strip()
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

@login_required(login_url='login')
def api_add_task(request):
    # Create a task owned by the authenticated account from the submitted JSON fields.
    # Returns: JSON containing the new database primary key, or HTTP 400 for other methods.
    if request.method == "POST":
        data = parse_json_body(request)
        if data is None:
            return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
        # Validate before writing so bad input yields 400 instead of a 500 (B-04).
        raw_title, raw_tags = data.get('title') or '', data.get('tags') or ''
        priority = data.get('priority') or 'medium'
        raw_due = data.get('due_date') or None
        if not all(isinstance(v, str) for v in (raw_title, raw_tags, priority)):
            return _task_error('Title, priority and tags must be strings.')
        title, tags = raw_title.strip(), raw_tags
        if not title:
            return _task_error('Task title is required.')
        if len(title) > Task._meta.get_field('title').max_length:
            return _task_error('Task title is too long.')
        if priority not in dict(Task.PRIORITY_CHOICES):
            return _task_error('Unknown priority.')
        if len(tags) > Task._meta.get_field('tags').max_length:
            return _task_error('Tags are too long.')
        due_date = None
        if raw_due:
            try:
                due_date = parse_date(str(raw_due))
            except ValueError:
                due_date = None
            if due_date is None:
                return _task_error('Invalid due date (expected YYYY-MM-DD).')
        task = Task.objects.create(
            user=request.user,
            title=title,
            priority=priority,
            due_date=due_date,
            tags=tags
        )
        return JsonResponse({'status': 'ok', 'task_id': task.id})
    return JsonResponse({'status': 'error'}, status=400)

@login_required(login_url='login')
def api_update_task_status(request):
    # Update only a task belonging to the caller, preventing cross-account task edits.
    # Returns: JSON success, or a not-found error when the task is not owned by the user.
    if request.method == "POST":
        data = parse_json_body(request)
        if data is None:
            return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
        new_status = data.get('status')
        if not isinstance(new_status, str) or new_status not in dict(Task.STATUS_CHOICES):
            return _task_error('Unknown task status.')
        try:
            task_id = int(data.get('task_id'))
        except (TypeError, ValueError):
            return _task_error('Invalid task id.')
        try:
            task = Task.objects.get(id=task_id, user=request.user)
            task.status = new_status
            task.save()
            return JsonResponse({'status': 'ok'})
        except Task.DoesNotExist:
            return JsonResponse({'status': 'error', 'msg': 'Task not found'}, status=404)
    # Non-POST requests previously fell through and returned None → HTTP 500 (B-04).
    return JsonResponse({'status': 'error'}, status=400)

@login_required(login_url='login')
def api_get_note_content(request):
    # Load a Markdown note, convert Obsidian wiki links, and find inbound mentions.
    # Parameters: the GET query parameter "name" identifies the requested note.
    # Returns: rendered HTML and backlink snippets, or a JSON error response.
    from ..rag_engine import get_user_paths
    note_name = request.GET.get('name')
    if not note_name:
        return JsonResponse({'status': 'error', 'msg': 'No note name provided.'}, status=400)

    paths = get_user_paths(request.user)
    target_file_name = f"{note_name}.md"
    current_file_path = None
    
    if os.path.exists(paths["notes_dir"]):
        for root, dirs, files in os.walk(paths["notes_dir"]):
            if target_file_name in files:
                current_file_path = os.path.join(root, target_file_name)
                break
                
    if not current_file_path:
        return JsonResponse({'status': 'error', 'msg': 'Note not found in the secure vault.'}, status=404)

    try:
        with open(current_file_path, 'r', encoding='utf-8') as f:
            raw_markdown = f.read()

        linked_mentions = []
        wiki_link_pattern = f"[[{note_name}]]"
        for root, dirs, files in os.walk(paths["notes_dir"]):
            for file in files:
                if file.endswith(".md") and file != target_file_name:
                    try:
                        with open(os.path.join(root, file), 'r', encoding='utf-8') as sf:
                            scan_content = sf.read()
                            if wiki_link_pattern in scan_content:
                                idx = scan_content.find(wiki_link_pattern)
                                snippet = scan_content[max(0, idx - 40):min(len(scan_content), idx + len(wiki_link_pattern) + 40)].replace('\n', ' ').strip()
                                linked_mentions.append({'title': file.replace(".md", ""), 'snippet': f"...{snippet}..."})
                    except Exception:
                        continue 

        # Convert each Obsidian link while preserving optional display-text aliases.
        def replace_wiki_links(match):
            link_text = match.group(1).strip()
            if '|' in link_text:
                note_target, note_display = link_text.split('|', 1)
            else:
                note_target, note_display = link_text, link_text
            return f'<a href="#" class="wiki-link text-[var(--active-accent)] border-b border-dashed border-[var(--active-accent)] hover:text-white transition-colors" data-note="{escape(note_target.strip())}">{escape(note_display.strip())}</a>'

        html_content = markdown.markdown(re.sub(r'\[\[(.*?)\]\]', replace_wiki_links, raw_markdown), extensions=['fenced_code', 'tables'])
        return JsonResponse({'status': 'ok', 'html_content': html_content, 'backlinks': linked_mentions})
    except Exception as e:
        return JsonResponse({'status': 'error', 'msg': str(e)}, status=500)

@login_required(login_url='login')
def api_sidebar_stats(request):
    # Aggregate the current user's task completion counts for the sidebar indicator.
    # Returns: JSON with completed, total, and integer percentage values.
    total_tasks = Task.objects.filter(user=request.user).count()
    done_tasks = Task.objects.filter(user=request.user, status='done').count()
    percent = int((done_tasks / total_tasks) * 100) if total_tasks > 0 else 0
    return JsonResponse({'status': 'ok', 'percent': percent, 'done': done_tasks, 'total': total_tasks})