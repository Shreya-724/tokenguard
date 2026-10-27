"""Endpoints for load tests. The same three views exist in both modes.

    /bench/allowed/    20 callers, each with a limit too big to ever reach
    /bench/blocked/    5 callers, each with 1 token and no refill: ~always 429
    /bench/distinct/   a new caller on every request (key creation, memory)
    /bench/mode/       what this server is running, so a run can check itself

BENCH_MODE=baseline leaves the decorator off, so the views do identical work
without tokenguard. Compare the two runs and what is left is the limiter.
"""

import os

from django.http import JsonResponse

from tokenguard.django import rate_limit

BASELINE = os.getenv("BENCH_MODE", "limited") == "baseline"


def _limit(**options):
    if BASELINE:
        return lambda view: view
    return rate_limit(key="api_key", **options)


@_limit(capacity=1e9, refill_rate=1e9)
def allowed(request):
    return JsonResponse({"ok": True})


@_limit(capacity=1, refill_rate=0.0001)
def blocked(request):
    return JsonResponse({"ok": True})


@_limit(capacity=10, refill_rate=1)
def distinct(request):
    return JsonResponse({"ok": True})


def mode(request):
    from django.conf import settings

    options = settings.TOKENGUARD
    return JsonResponse(
        {
            "mode": "baseline" if BASELINE else "limited",
            "metrics": bool(options.get("METRICS")),
            "live_rules": bool(options.get("LIVE_RULES")),
            "redis_url": options.get("REDIS_URL"),
        }
    )
