"""Test-only middleware: the e2e live_server shares ONE in-memory SQLite connection
between its request threads; parallel page requests (note + editor names) then fail
with "bad parameter or other API misuse". Serialising requests in tests avoids that."""
import threading

_LOCK = threading.RLock()


class SerialRequestsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with _LOCK:
            return self.get_response(request)
