"""PWA endpoints (Round 5, F4): web app manifest and the service worker at the site root."""
import json
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.templatetags.static import static
from django.views.decorators.cache import cache_control

SW_FILE = Path(settings.BASE_DIR) / "static" / "js" / "sw.js"


@cache_control(max_age=3600, public=True)
def manifest(request):
    data = {
        "name": "Second Brain", "short_name": "Second Brain", "lang": "ru",
        "description": "Заметки Obsidian, задачи и ИИ — с любого устройства.",
        "start_url": "/", "scope": "/", "display": "standalone", "orientation": "any",
        "background_color": "#0D0D12", "theme_color": "#0D0D12",
        "icons": [
            {"src": static("icons/icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("icons/icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": static("icons/icon-maskable-512.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            {"src": static("icons/icon.svg"), "sizes": "any", "type": "image/svg+xml"},
        ],
        "shortcuts": [
            {"name": "Эта неделя", "url": "/weekly/"},
            {"name": "Заметки", "url": "/notes/"},
        ],
    }
    return HttpResponse(json.dumps(data, ensure_ascii=False), content_type="application/manifest+json; charset=utf-8")


def service_worker(request):
    """Served from / (not /static/) so its scope is the whole site; never cached by HTTP."""
    body = SW_FILE.read_text(encoding="utf-8").replace("__STATIC__", static(""))
    response = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache"
    return response
