"""Named URL routes for browser pages, authenticated APIs, and superuser tools."""
from django.urls import path, re_path
from . import views
from . import api_v1
from .views import agent_api, notes_api, tokens_api

urlpatterns = [
    # Public authentication pages manage registration, login, and session exit.
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),

    # Main user workspace pages; each route maps to a template-oriented page view.
    path('', views.home_view, name='home'),
    path('chat/', views.ai_chat_view, name='chat'),
    path('notes/', views.notes_view, name='notes'),
    path('tasks/', views.tasks_view, name='tasks'),
    path('settings/', views.settings_view, name='settings'),
    
    # JSON APIs used by chat, settings, note rendering, and sidebar status widgets.
    path('api/send-message/', views.api_chat_message, name='api_send_message'),
    path('api/save-settings/', views.api_save_settings, name='api_save_settings'),
    path('api/get-note/', views.api_get_note_content, name='api_get_note'),
    path('api/sidebar-stats/', views.api_sidebar_stats, name='api_sidebar_stats'),
    
    # Task creation and status mutation endpoints used by the task UI.
    path('api/add-task/', views.api_add_task, name='api_add_task'),
    path('api/update-task/', views.api_update_task_status, name='api_update_task'),
    path('api/delete-task/', views.api_delete_task, name='api_delete_task'),
    path('api/tasks/sync/', views.api_tasks_sync, name='api_tasks_sync'),

    # Note editor (Round 4): read raw text + hash, save with conflict check, create/delete/rename.
    path('api/notes/names/', notes_api.notes_names, name='api_notes_names'),
    path('api/notes/meta/', notes_api.notes_meta, name='api_notes_meta'),
    path('api/notes/raw/', notes_api.notes_raw, name='api_notes_raw'),
    path('api/notes/save/', notes_api.notes_save, name='api_notes_save'),
    path('api/notes/create/', notes_api.notes_create, name='api_notes_create'),
    path('api/notes/delete/', notes_api.notes_delete, name='api_notes_delete'),
    path('api/notes/rename/', notes_api.notes_rename, name='api_notes_rename'),

    # AI agent (Round 4): run → batch of proposed changes → apply / reject / revert.
    path('api/agent/run/', agent_api.agent_run, name='api_agent_run'),
    path('api/agent/batch/<int:batch_id>/apply/', agent_api.agent_apply, name='api_agent_apply'),
    path('api/agent/batch/<int:batch_id>/reject/', agent_api.agent_reject, name='api_agent_reject'),
    path('api/agent/batch/<int:batch_id>/revert/', agent_api.agent_revert, name='api_agent_revert'),

    # API tokens in Settings (Round 4): shown once, only the hash is stored.
    path('api/tokens/create/', tokens_api.token_create, name='api_tokens_create'),
    path('api/tokens/revoke/', tokens_api.token_revoke, name='api_tokens_revoke'),

    # REST API v1 (Round 4, Link2Note contract docs/link2note/API_CONTRACT.md). Token-only,
    # trailing slash optional (the bot calls /api/v1/notes, older clients /api/v1/notes/).
    re_path(r'^api/v1/health/?$', api_v1.health, name='api_v1_health'),
    re_path(r'^api/v1/sync/?$', api_v1.sync_status, name='api_v1_sync'),
    re_path(r'^api/v1/schema/?$', api_v1.schema, name='api_v1_schema'),
    re_path(r'^api/v1/notes/?$', api_v1.notes_collection, name='api_v1_notes'),
    re_path(r'^api/v1/notes/search/?$', api_v1.notes_search, name='api_v1_notes_search'),
    re_path(r'^api/v1/notes/lookup/?$', api_v1.notes_lookup, name='api_v1_notes_lookup'),
    re_path(r'^api/v1/notes/append/?$', api_v1.notes_append, name='api_v1_notes_append'),
    re_path(r'^api/v1/notes/(?P<rest>.+)$', api_v1.note_item, name='api_v1_note_item'),
    re_path(r'^api/v1/folders/?$', api_v1.folders, name='api_v1_folders'),
    re_path(r'^api/v1/capture/?$', api_v1.capture, name='api_v1_capture'),
    re_path(r'^api/v1/tasks/?$', api_v1.tasks_collection, name='api_v1_tasks'),
    re_path(r'^api/v1/tasks/(?P<task_id>[^/]+)/?$', api_v1.task_item, name='api_v1_task_item'),
    re_path(r'^api/v1/ask/?$', api_v1.ask, name='api_v1_ask'),
    re_path(r'^api/v1/agent/?$', api_v1.agent_run, name='api_v1_agent'),
    re_path(r'^api/v1/agent/(?P<batch_id>\d+)/(?P<action>apply|reject|revert)/?$', api_v1.agent_action,
            name='api_v1_agent_action'),

    # Liveness/readiness probe for Docker (no login, no AI, checks the DB).
    path('healthz/', views.healthz, name='healthz'),

    # Superuser-only administrative pages and row mutation endpoints.
    path('system-matrix/', views.admin_dashboard_view, name='admin_dashboard'),
    path('api/admin/update-row/', views.api_admin_update_row, name='api_admin_update'),
    path('api/admin/delete-row/', views.api_admin_delete_row, name='api_admin_delete'),
]