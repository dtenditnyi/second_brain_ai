"""Session JSON endpoints for the chat "Agent" mode (Round 4 / G-E3, G-E6). CSRF-protected."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from .. import agent
from .utils import parse_json_body


def _post(request):
    if request.method != "POST":
        return None, JsonResponse({"status": "error", "msg": "POST only."}, status=405)
    data = parse_json_body(request)
    if data is None:
        return None, JsonResponse({"status": "error", "msg": "Malformed JSON body."}, status=400)
    return data, None


def _batch_action(fn):
    try:
        return JsonResponse({"status": "ok", "batch": agent.batch_json(fn())})
    except agent.AgentError as error:
        return JsonResponse({"status": "error", "msg": str(error)}, status=error.status)


@login_required(login_url='login')
def agent_run(request):
    data, error = _post(request)
    if error:
        return error
    message = data.get("message")
    if not isinstance(message, str) or not message.strip():
        return JsonResponse({"status": "error", "msg": "Пустой запрос."}, status=400)
    run = agent.run_agent(request.user, message)
    return JsonResponse({"status": "ok", **agent.run_json(run)})


@login_required(login_url='login')
def agent_apply(request, batch_id):
    data, error = _post(request)
    if error:
        return error
    indices = data.get("indices")
    if indices is not None and (not isinstance(indices, list) or not all(isinstance(i, int) for i in indices)):
        return JsonResponse({"status": "error", "msg": "indices must be a list of integers."}, status=400)
    return _batch_action(lambda: agent.apply_batch(request.user, batch_id, indices=indices))


@login_required(login_url='login')
def agent_reject(request, batch_id):
    _, error = _post(request)
    return error or _batch_action(lambda: agent.reject_batch(request.user, batch_id))


@login_required(login_url='login')
def agent_revert(request, batch_id):
    _, error = _post(request)
    return error or _batch_action(lambda: agent.revert_batch(request.user, batch_id))
