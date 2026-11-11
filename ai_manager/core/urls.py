"""Named URL routes for browser pages, authenticated APIs, and superuser tools."""
from django.urls import path
from . import views
from .views import notes_api

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

    # Liveness/readiness probe for Docker (no login, no AI, checks the DB).
    path('healthz/', views.healthz, name='healthz'),

    # Superuser-only administrative pages and row mutation endpoints.
    path('system-matrix/', views.admin_dashboard_view, name='admin_dashboard'),
    path('api/admin/update-row/', views.api_admin_update_row, name='api_admin_update'),
    path('api/admin/delete-row/', views.api_admin_delete_row, name='api_admin_delete'),
]