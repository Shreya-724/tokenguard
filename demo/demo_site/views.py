from django.http import JsonResponse
from rest_framework.response import Response
from rest_framework.views import APIView

from tokenguard.django import rate_limit
from tokenguard.django.conf import effective_config, get_client


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
