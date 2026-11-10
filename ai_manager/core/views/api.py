"""JSON endpoints connecting browser interactions to Django models and RAG services."""
import json
import logging
import os
import re
import markdown
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required

from ..models import Task, ChatMessage, get_user_settings
from .. import rag_engine
from .utils import parse_json_body

logger = logging.getLogger(__name__)

@csrf_exempt
@login_required(login_url='login')
def api_chat_message(request):
    # Validate a chat POST, persist both turns, and pass optional file filters to RAG.
    # Parameters: request contains JSON with a message and selected file names.
    # Returns: a JSON reply on success, or HTTP 400 when the request is unusable.
    if request.method == "POST":
        data = parse_json_body(request)
        if data is None:
            return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
        user_message = data.get('message', '')
        # Accept both current and legacy browser key spellings, then discard
        # malformed entries before the filenames reach the retrieval layer.
        selected_files = data.get('selected_files', data.get('selectedFiles', []))
        if not isinstance(selected_files, list):
            selected_files = []
        selected_files = [file_name for file_name in selected_files if isinstance(file_name, str)]
        
        if user_message:
            ChatMessage.objects.create(user=request.user, role='user', content=user_message)
            ai_response = rag_engine.ask_second_brain(user_message, request.user, selected_files)
            ChatMessage.objects.create(user=request.user, role='ai', content=ai_response)
            return JsonResponse({'status': 'ok', 'reply': ai_response})
    return JsonResponse({'status': 'error'}, status=400)

@csrf_exempt
@login_required(login_url='login')
def api_save_settings(request):
    # Persist account identity separately from per-user application preferences.
    # Parameters: request.body is JSON produced by settings.js.
    # Returns: JSON status; the RAG cache is reset so subsequent turns use new settings.
    if request.method == "POST":
        data = parse_json_body(request)
        if data is None:
            return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
        username = data.get('username', data.get('display_name', request.user.username))
        email = data.get('email', request.user.email)

        request.user.username = str(username).strip()
        request.user.email = str(email).strip()
        request.user.save()

        settings = get_user_settings(request.user)
        
        settings.display_name = data.get('display_name', settings.display_name)
        settings.theme = data.get('theme', settings.theme)
        settings.accent_color = data.get('accent_color', settings.accent_color)
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
        settings.github_repo_url = data.get('github_repo_url', settings.github_repo_url).strip()
        settings.github_token = data.get('github_token', settings.github_token).strip()
        settings.save()
        logger.info(
            "User settings updated: AI Strategy -> %s; Temperature -> %.1f.",
            settings.ai_strategy,
            settings.temperature,
        )
        
        rag_engine.reset_chat_engine(request.user.id)
        return JsonResponse({'status': 'ok'})
    return JsonResponse({'status': 'error'}, status=400)

@csrf_exempt
@login_required(login_url='login')
def api_add_task(request):
    # Create a task owned by the authenticated account from the submitted JSON fields.
    # Returns: JSON containing the new database primary key, or HTTP 400 for other methods.
    if request.method == "POST":
        data = parse_json_body(request)
        if data is None:
            return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
        task = Task.objects.create(
            user=request.user,
            title=data.get('title'),
            priority=data.get('priority', 'medium'),
            due_date=data.get('due_date') or None,
            tags=data.get('tags', '')
        )
        return JsonResponse({'status': 'ok', 'task_id': task.id})
    return JsonResponse({'status': 'error'}, status=400)

@csrf_exempt
@login_required(login_url='login')
def api_update_task_status(request):
    # Update only a task belonging to the caller, preventing cross-account task edits.
    # Returns: JSON success, or a not-found error when the task is not owned by the user.
    if request.method == "POST":
        data = parse_json_body(request)
        if data is None:
            return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
        try:
            task = Task.objects.get(id=data.get('task_id'), user=request.user)
            task.status = data.get('status')
            task.save()
            return JsonResponse({'status': 'ok'})
        except Task.DoesNotExist:
            return JsonResponse({'status': 'error', 'msg': 'Task not found'}, status=404)

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
            return f'<a href="#" class="wiki-link text-[var(--active-accent)] border-b border-dashed border-[var(--active-accent)] hover:text-white transition-colors" data-note="{note_target.strip()}">{note_display.strip()}</a>'

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