import json

from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.views import View
from rest_framework.response import Response
from rest_framework.views import APIView

from tokenguard.budget import Budget
from tokenguard.django import rate_limit
from tokenguard.django.conf import effective_config, get_client
from tokenguard.django.llm import llm_cost, llm_usage, user_model
from tokenguard.llm import MODELS, estimate_tokens


def health(request):
    """Exempt from limiting (see EXEMPT in settings)."""
    return JsonResponse({"status": "ok"})


def ping(request):
    """Cheap endpoint: uses DEFAULT_RULE from the middleware."""
    return JsonResponse({"pong": True})


@rate_limit(capacity=20, refill_rate=0.5, key="user", cost=5)
def report(request):
    """Expensive endpoint: each call costs 5 tokens, so only 4 per burst."""
    return JsonResponse({"report": "generated"})


def login(request):
    """Login-style endpoint: limited by the "login" entry in RULES."""
    return JsonResponse({"ok": True})


class ChatView(APIView):
    """A DRF view. The limit is applied in urls.py around as_view()."""

    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request):
        return Response({"reply": "hello"})


def config(request):
    """Shows the settings tokenguard is using and whether Redis answers."""
    try:
        redis_ok = bool(get_client().ping())
    except Exception as exc:  # demo only
        redis_ok = f"error: {exc}"
    return JsonResponse({"tokenguard": effective_config(), "redis_ok": redis_ok})


@method_decorator(
    rate_limit(capacity=10, refill_rate=0.05, key="user"), name="dispatch"
)
class SummaryView(View):
    """Class-based view limited via method_decorator on dispatch."""

    def get(self, request):
        return JsonResponse({"summary": "ok"})


def _read_completion_request(request):
    """Validate a JSON completion request. Returns (body, error_response)."""
    if request.method != "POST":
        return None, JsonResponse({"error": "POST only"}, status=405)
    try:
        body = json.loads(request.body)
    except ValueError:
        return None, JsonResponse({"error": "invalid JSON"}, status=400)
    if not isinstance(body, dict) or not isinstance(body.get("prompt"), str):
        return None, JsonResponse({"error": "prompt must be a string"}, status=400)
    if body.get("model", "small") not in MODELS:
        return None, JsonResponse({"error": "unknown model"}, status=400)
    return body, None


def _mock_usage(body):
    """Pretend to be the model reporting what it really used."""
    max_tokens = body.get("max_tokens")
    default = min(max_tokens, 40) if isinstance(max_tokens, int) else 40
    return {
        "prompt_tokens": estimate_tokens(body["prompt"]),
        "completion_tokens": body.get("mock_completion_tokens", default),
    }


def _complete(request):
    body, error = _read_completion_request(request)
    if error:
        return error
    if body.get("simulate_error"):
        return JsonResponse({"error": "upstream_failed"}, status=502)
    return JsonResponse({"text": "This is a canned reply.", "usage": _mock_usage(body)})


@rate_limit(
    capacity=10_000,
    refill_rate=50,
    key=user_model,  # a separate burst bucket per (user, model)
    cost=llm_cost(),  # tokens + dollars + the model's weight (large counts 5x)
    usage=llm_usage(),  # settle the estimate against the real usage
)
def complete(request):
    """Mock LLM: charged by estimated tokens, settled by real usage."""
    return _complete(request)


@rate_limit(capacity=10_000, refill_rate=50, key="user", cost=llm_cost())
def complete_manual(request):
    """Same, but the view settles the charge itself."""
    body, error = _read_completion_request(request)
    if error:
        return error
    usage = _mock_usage(body)
    charge = getattr(request, "tokenguard", None)
    if charge:
        charge.reconcile(usage["prompt_tokens"] + usage["completion_tokens"])
    return JsonResponse({"text": "This is a canned reply.", "usage": usage})


@rate_limit(
    capacity=10_000,
    refill_rate=50,
    key=user_model,  # burst: per (user, model) ...
    budget_key="user",  # ... but ONE budget per user across models
    cost=llm_cost(),
    usage=llm_usage(),
    budget=Budget(  # deliberately tiny, so the demo hits them quickly
        daily_tokens=1_000,
        daily_usd=0.01,
        monthly_tokens=20_000,
        monthly_usd=0.50,
    ),
)
def budgeted(request):
    """Same mock, with daily and monthly budgets on top of the burst bucket."""
    return _complete(request)
