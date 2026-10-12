"""Shared logic used by both the decorator and the middleware."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.http import HttpResponse, JsonResponse

from tokenguard.bucket import Decision
from tokenguard.django.conf import check_fail_mode, get_client, get_setting
from tokenguard.django.keys import KeyFunc
from tokenguard.errors import RedisUnavailableError
from tokenguard.redis_bucket import RedisTokenBucket

logger = logging.getLogger("tokenguard")

CostFunc = Callable[[Any], float]  # request -> tokens to charge
UsageFunc = Callable[[Any, Any], "float | None"]  # (request, response) -> actual


@dataclass(frozen=True)
class Rule:
    capacity: float
    refill_rate: float
    key: KeyFunc
    scope: str  # namespaces the bucket so different rules never share one
    fail_mode: str | None = None  # None -> the global FAIL_MODE setting
    cost: float | CostFunc = 1  # a number, or a function of the request
    usage: UsageFunc | None = None  # real usage, to settle the estimate afterwards

    def cost_for(self, request: Any) -> float:
        return float(self.cost(request) if callable(self.cost) else self.cost)


class Charge:
    """What a request was charged up front, so it can be settled afterwards.

    Available to views as `request.tokenguard`:
        request.tokenguard.reconcile(actual_tokens)
    Only the first settlement counts, so calling it twice is harmless.
    """

    def __init__(self, bucket: RedisTokenBucket, cost: float, remaining: float):
        self._bucket = bucket
        self.cost = cost
        self.remaining = remaining
        self.settled = False

    def reconcile(self, actual: float) -> float:
        """Replace the estimate with real usage. Returns the tokens now left."""
        if self.settled:
            return self.remaining
        self.settled = True
        delta = max(0.0, float(actual)) - self.cost  # >0 charge extra, <0 refund
        if delta == 0:
            return self.remaining
        try:
            self.remaining = self._bucket.adjust(delta)
        except RedisUnavailableError as exc:
            # The work is already done; never fail the response over bookkeeping.
            logger.warning("Redis unavailable, could not reconcile usage: %s", exc)
        return self.remaining

    def refund(self) -> float:
        """The request failed: give back everything it was charged."""
        return self.reconcile(0)


@dataclass
class Outcome:
    rejection: HttpResponse | None = None  # a ready 413/429/503, or None to proceed
    charge: Charge | None = None  # None if rejected, or Redis was down (fail-open)


def _num(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


def add_headers(response: HttpResponse, rule: Rule, remaining: float) -> None:
    """X-RateLimit-* headers. Reset = unix time when the bucket is full again."""
    missing = max(0.0, rule.capacity - remaining)
    response["X-RateLimit-Limit"] = str(int(rule.capacity))
    response["X-RateLimit-Remaining"] = str(max(0, math.floor(remaining)))
    response["X-RateLimit-Reset"] = str(
        math.ceil(time.time() + missing / rule.refill_rate)
    )


def too_many_requests(rule: Rule, decision: Decision) -> HttpResponse:
    """429: the bucket is empty right now. Waiting will help."""
    response = JsonResponse(
        {"error": "rate_limited", "retry_after": round(decision.retry_after, 3)},
        status=429,
    )
    response["Retry-After"] = str(math.ceil(decision.retry_after))
    add_headers(response, rule, decision.remaining)
    return response


def request_too_large(rule: Rule, cost: float) -> HttpResponse:
    """413: this single request costs more than the bucket can ever hold.

    Not a 429 and no Retry-After: waiting will never make it fit. The caller
    has to send a smaller request (shorter prompt or lower max_tokens).
    """
    response = JsonResponse(
        {
            "error": "request_too_large",
            "cost": _num(cost),
            "capacity": _num(rule.capacity),
            "message": "This request needs more tokens than the limit allows "
            "at once. Shorten the prompt or lower max_tokens.",
        },
        status=413,
    )
    response["X-RateLimit-Limit"] = str(int(rule.capacity))
    return response


def unavailable_response() -> HttpResponse:
    return JsonResponse({"error": "rate_limiter_unavailable"}, status=503)


def enforce(request: Any, rule: Rule) -> Outcome:
    """Charge the request against its bucket (before the view runs)."""
    fail_mode = rule.fail_mode or get_setting("FAIL_MODE")
    check_fail_mode(fail_mode)

    cost = rule.cost_for(request)
    if cost > rule.capacity:
        # Decided locally: it can never fit, so it is rejected even if Redis is down.
        return Outcome(rejection=request_too_large(rule, cost))

    bucket = RedisTokenBucket(
        get_client(),
        f"{rule.scope}:{rule.key(request)}",
        rule.capacity,
        rule.refill_rate,
        key_prefix=f"{get_setting('KEY_PREFIX')}:",
    )
    try:
        decision = bucket.allow(cost)
    except RedisUnavailableError as exc:
        if fail_mode == "open":
            logger.warning("Redis unavailable, failing OPEN (%s): %s", rule.scope, exc)
            return Outcome()
        logger.error("Redis unavailable, failing CLOSED (%s): %s", rule.scope, exc)
        return Outcome(rejection=unavailable_response())

    if not decision.allowed:
        return Outcome(rejection=too_many_requests(rule, decision))

    charge = Charge(bucket, cost, decision.remaining)
    request.tokenguard = charge
    return Outcome(charge=charge)


def settle(
    request: Any, rule: Rule, charge: Charge | None, response: HttpResponse | None
) -> None:
    """After the view ran: refund on failure, or reconcile against real usage.

    response=None means the view raised an exception. Server errors (5xx) and
    exceptions are refunded in full. Client errors (4xx) stay charged, so
    flooding the API with invalid requests still costs the sender.
    """
    if charge is None or charge.settled:
        return
    if response is None or response.status_code >= 500:
        charge.refund()
        return
    if rule.usage is None:
        return
    try:
        actual = rule.usage(request, response)
    except Exception:
        logger.exception("tokenguard usage function failed; keeping the estimate")
        return
    if actual is not None:
        charge.reconcile(actual)
