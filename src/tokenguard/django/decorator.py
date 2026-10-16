"""@rate_limit for function views, class-based views and DRF views."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from typing import Any

from tokenguard.budget import Budget, Cost
from tokenguard.django.engine import (
    CostFunc,
    Rule,
    UsageFunc,
    add_headers,
    enforce,
    settle,
)
from tokenguard.django.keys import KeyFunc, resolve_key


def _find_request(args: tuple[Any, ...]):
    # Function view: (request, ...). Method on a class: (self, request, ...).
    for candidate in args[:2]:
        if hasattr(candidate, "META") and hasattr(candidate, "method"):
            return candidate
    raise TypeError("rate_limit could not find a request in the view's arguments")


def rate_limit(
    capacity: float,
    refill_rate: float,
    key: str | KeyFunc | None = None,
    cost: float | Cost | CostFunc = 1,
    fail_mode: str | None = None,
    scope: str | None = None,
    usage: UsageFunc | None = None,
    budget: Budget | None = None,
    budget_key: str | KeyFunc | None = None,
    algorithm: str | None = None,
) -> Callable:
    """Limit a view. The decorator wins over middleware rules for the same view.

    key:        "user" (default, falls back to IP), "ip", "api_key", "endpoint",
                "user_endpoint", "tokenguard.django.llm.user_model" (a bucket per
                user and model), a dotted path, or any callable(request) -> str.
    cost:       tokens charged: a number, a Cost (tokens, dollars, model weight),
                or a callable(request) returning either.
    usage:      optional callable(request, response) -> tokens really used, or a
                Usage, or None. The difference from the estimate is refunded or
                charged afterwards.
    budget:     optional daily/monthly caps (tokens and/or dollars) that are
                checked together with the burst bucket, atomically.
    budget_key: who owns the budget (default: same as key). Use "user" to share
                one budget across a per-model burst key.
    algorithm:  "token_bucket" or "fixed_window" (default: the ALGORITHM setting).
                Budgets always use the token bucket.
    fail_mode:  "open" or "closed" when Redis is down (default: global setting).
    scope:      bucket namespace; defaults to the view's module + name.

    A cost larger than a limit can ever hold is rejected with 413.
    If the view raises, or returns a 5xx, the whole charge is refunded.
    """
    key_func = resolve_key(key)
    budget_key_func = resolve_key(budget_key) if budget_key is not None else None

    def decorator(view: Callable) -> Callable:
        if asyncio.iscoroutinefunction(view):
            raise TypeError("rate_limit does not support async views yet")
        default_scope = (
            f"{getattr(view, '__module__', '')}.{getattr(view, '__qualname__', 'view')}"
        )
        rule = Rule(
            capacity=capacity,
            refill_rate=refill_rate,
            key=key_func,
            scope=scope or default_scope,
            fail_mode=fail_mode,
            cost=cost,
            usage=usage,
            budget=budget,
            budget_key=budget_key_func,
            algorithm=algorithm,
        )

        @functools.wraps(view)
        def wrapper(*args: Any, **kwargs: Any):
            request = _find_request(args)
            outcome = enforce(request, rule)
            if outcome.rejection is not None:
                return outcome.rejection
            try:
                response = view(*args, **kwargs)
            except Exception:
                settle(request, rule, outcome.charge, None)
                raise
            settle(request, rule, outcome.charge, response)
            if outcome.charge is not None:
                add_headers(
                    response,
                    rule,
                    outcome.charge.remaining,
                    outcome.charge.reset_after,
                )
            return response

        # The middleware looks for this marker so it does not charge a second time.
        wrapper.tokenguard_rule = rule  # type: ignore[attr-defined]
        return wrapper

    return decorator
