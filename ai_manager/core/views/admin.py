"""Superuser-only dashboard and JSON operations for administrative data tables."""
import json
from django.core.exceptions import ObjectDoesNotExist
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import user_passes_test
from django.contrib.auth.models import User

from ..models import UserSettings, Task, ChatMessage
from .utils import parse_json_body

@user_passes_test(lambda u: u.is_superuser, login_url='login')
def admin_dashboard_view(request):
    # Load the administrative datasets and render the isolated Core Matrix UI.
    # Parameters: request is restricted to authenticated superusers by the decorator.
    # Returns: the admin dashboard with users, preferences, tasks, and recent messages.
    context = {
        'users': User.objects.all().order_by('id'),
        'settings': UserSettings.objects.all().order_by('id'),
        'tasks': Task.objects.all().order_by('-id'),
        'messages': ChatMessage.objects.all().order_by('-id')[:100],
    }
    return render(request, 'admin_dashboard.html', context)

@user_passes_test(lambda u: u.is_superuser, login_url='login')
def api_admin_update_row(request):
    # Dispatch a table-row update to the appropriate Django model using posted fields.
    # Returns: JSON status; lookup, validation, and persistence errors become HTTP 500.
    if request.method == "POST":
        try:
            data = parse_json_body(request)
            if data is None:
                return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
            target_table, row_id, fields = data.get('table'), data.get('id'), data.get('fields', {})

            if target_table == 'users':
                obj = User.objects.get(id=row_id)
                # Q11: a superuser cannot demote themself (would lock them out).
                if obj.pk == request.user.pk and fields.get('is_superuser', True) not in ['true', True]:
                    return JsonResponse({'status': 'error',
                                         'msg': 'You cannot remove your own superuser rights.'}, status=400)
                obj.username, obj.email = fields.get('username', obj.username), fields.get('email', obj.email)
                if 'is_superuser' in fields:  # a missing key no longer demotes the user
                    obj.is_superuser = fields.get('is_superuser') in ['true', True]
                obj.save()
            elif target_table == 'settings':
                obj = UserSettings.objects.get(id=row_id)
                for f in ['display_name', 'theme', 'accent_color', 'ai_strategy', 'github_repo_url']:
                    setattr(obj, f, fields.get(f, getattr(obj, f)))
                raw_temperature = fields.get('temperature')
                if raw_temperature not in (None, ''):
                    try:
                        obj.temperature = float(raw_temperature)
                    except (TypeError, ValueError):
                        return JsonResponse({'status': 'error', 'msg': 'Temperature must be a number.'}, status=400)
                obj.save()
            elif target_table == 'tasks':
                obj = Task.objects.get(id=row_id)
                for f in ['title', 'status', 'priority', 'tags']:
                    setattr(obj, f, fields.get(f, getattr(obj, f)))
                obj.due_date = fields.get('due_date') or None
                obj.save()
            elif target_table == 'messages':
                obj = ChatMessage.objects.get(id=row_id)
                obj.role, obj.content = fields.get('role', obj.role), fields.get('content', obj.content)
                obj.save()
            else:
                return JsonResponse({'status': 'error', 'msg': 'Target table unrecognized.'}, status=400)
            return JsonResponse({'status': 'ok'})
        except ObjectDoesNotExist:
            return JsonResponse({'status': 'error', 'msg': 'Row not found.'}, status=404)
        except Exception as e:
            return JsonResponse({'status': 'error', 'msg': str(e)}, status=500)
    return JsonResponse({'status': 'error'}, status=400)

@user_passes_test(lambda u: u.is_superuser, login_url='login')
def api_admin_delete_row(request):
    # Delete a selected row from an explicit allowlist of administrative models.
    # Returns: JSON status or a client/server error when the target cannot be deleted.
    if request.method == "POST":
        try:
            data = parse_json_body(request)
            if data is None:
                return JsonResponse({'status': 'error', 'msg': 'Malformed JSON body.'}, status=400)
            models_map = {'users': User, 'settings': UserSettings, 'tasks': Task, 'messages': ChatMessage}
            if data.get('table') in models_map:
                # Q11: deleting your own account from Core Matrix is refused.
                if data.get('table') == 'users' and str(data.get('id')) == str(request.user.pk):
                    return JsonResponse({'status': 'error', 'msg': 'You cannot delete your own account.'}, status=400)
                models_map[data.get('table')].objects.filter(id=data.get('id')).delete()
                return JsonResponse({'status': 'ok'})
            return JsonResponse({'status': 'error', 'msg': 'Invalid model context.'}, status=400)
        except Exception as e:
            return JsonResponse({'status': 'error', 'msg': str(e)}, status=500)
    return JsonResponse({'status': 'error'}, status=400)