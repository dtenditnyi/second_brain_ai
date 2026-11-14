"""/healthz/ — container health probe (Round 3 / G-B1).

No login, no AI, no vault access: it only proves that Django answers and the
database is reachable. Used by the docker-compose healthcheck and deploy scripts.
"""
import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache

logger = logging.getLogger(__name__)


@never_cache
def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception as error:  # any DB failure → unhealthy
        logger.error("healthz: database check failed: %s", type(error).__name__)
        return JsonResponse({"status": "error", "db": "error"}, status=503)
    return JsonResponse({"status": "ok", "db": "ok"})
