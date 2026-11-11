"""Named URL routes for browser pages, authenticated APIs, and superuser tools."""
from django.urls import path
from . import views 

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

    # Liveness/readiness probe for Docker (no login, no AI, checks the DB).
    path('healthz/', views.healthz, name='healthz'),

    # Superuser-only administrative pages and row mutation endpoints.
    path('system-matrix/', views.admin_dashboard_view, name='admin_dashboard'),
    path('api/admin/update-row/', views.api_admin_update_row, name='api_admin_update'),
    path('api/admin/delete-row/', views.api_admin_delete_row, name='api_admin_delete'),
]