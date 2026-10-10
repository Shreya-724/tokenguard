"""Shared logic used by both the decorator and the middleware."""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Any

from django.http import HttpResponse, JsonResponse

from tokenguard.bucket import Decision
from tokenguard.django.conf import check_fail_mode, get_client, get_setting
from tokenguard.django.keys import KeyFunc
from tokenguard.errors import RedisUnavailableError
from tokenguard.redis_bucket import RedisTokenBucket

logger = logging.getLogger("tokenguard")


@dataclass(frozen=True)
class Rule:
    capacity: float
    refill_rate: float
    key: KeyFunc
    scope: str  # namespaces the bucket so different rules never share one
    fail_mode: str | None = None  # None -> the global FAIL_MODE setting
    cost: float = 1


def add_headers(response: HttpResponse, rule: Rule, decision: Decision) -> None:
    """X-RateLimit-* headers. Reset = unix time when the bucket is full again."""
    missing = max(0.0, rule.capacity - decision.remaining)
    response["X-RateLimit-Limit"] = str(int(rule.capacity))
    response["X-RateLimit-Remaining"] = str(max(0, math.floor(decision.remaining)))
    response["X-RateLimit-Reset"] = str(
        math.ceil(time.time() + missing / rule.refill_rate)
    )


def too_many_requests(rule: Rule, decision: Decision) -> HttpResponse:
    if math.isinf(decision.retry_after):
        # The request costs more than the bucket can ever hold: waiting won't help.
        response = JsonResponse(
            {"error": "cost_exceeds_capacity", "retry_after": None}, status=429
        )
    else:
        response = JsonResponse(
            {"error": "rate_limited", "retry_after": round(decision.retry_after, 3)},
            status=429,
        )
        response["Retry-After"] = str(math.ceil(decision.retry_after))
    add_headers(response, rule, decision)
    return response


def unavailable_response() -> HttpResponse:
    return JsonResponse({"error": "rate_limiter_unavailable"}, status=503)


def enforce(request: Any, rule: Rule) -> tuple[Decision | None, HttpResponse | None]:
    """Charge the request against its bucket.

    Returns (decision, rejection). `rejection` is a ready 429/503 response, or
    None if the request may proceed. `decision` is None when Redis was down.
    """
    fail_mode = rule.fail_mode or get_setting("FAIL_MODE")
    check_fail_mode(fail_mode)
    bucket = RedisTokenBucket(
        get_client(),
        f"{rule.scope}:{rule.key(request)}",
        rule.capacity,
        rule.refill_rate,
        key_prefix=f"{get_setting('KEY_PREFIX')}:",
    )
    try:
        decision = bucket.allow(rule.cost)
    except RedisUnavailableError as exc:
        if fail_mode == "open":
            logger.warning("Redis unavailable, failing OPEN (%s): %s", rule.scope, exc)
            return None, None
        logger.error("Redis unavailable, failing CLOSED (%s): %s", rule.scope, exc)
        return None, unavailable_response()

    if decision.allowed:
        return decision, None
    return decision, too_many_requests(rule, decision)
