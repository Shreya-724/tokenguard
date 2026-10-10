"""@rate_limit for function views, class-based views and DRF views."""

from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from typing import Any

from tokenguard.django.engine import Rule, add_headers, enforce
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
    cost: float = 1,
    fail_mode: str | None = None,
    scope: str | None = None,
) -> Callable:
    """Limit a view. The decorator wins over middleware rules for the same view.

    key:       "user" (default, falls back to IP), "ip", "api_key", "endpoint",
               "user_endpoint", a dotted path, or any callable(request) -> str.
    cost:      tokens charged per request.
    fail_mode: "open" or "closed" when Redis is down (default: global setting).
    scope:     bucket namespace; defaults to the view's module + name.
    """
    key_func = resolve_key(key)

    def decorator(view: Callable) -> Callable:
        if asyncio.iscoroutinefunction(view):
            raise TypeError("rate_limit does not support async views yet")
        rule = Rule(
            capacity=capacity,
            refill_rate=refill_rate,
            key=key_func,
            scope=scope
            or f"{getattr(view, '__module__', '')}.{getattr(view, '__qualname__', 'view')}",
            fail_mode=fail_mode,
            cost=cost,
        )

        @functools.wraps(view)
        def wrapper(*args: Any, **kwargs: Any):
            request = _find_request(args)
            decision, rejection = enforce(request, rule)
            if rejection is not None:
                return rejection
            response = view(*args, **kwargs)
            if decision is not None:
                add_headers(response, rule, decision)
            return response

        # The middleware looks for this marker so it does not charge a second time.
        wrapper.tokenguard_rule = rule  # type: ignore[attr-defined]
        return wrapper

    return decorator
