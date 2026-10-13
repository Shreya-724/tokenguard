"""Middleware: DEFAULT_RULE for every request, with per-route overrides.

Precedence (highest first):
  1. EXEMPT paths            -> never limited
  2. @rate_limit on the view -> the decorator's rule (middleware stays out)
  3. a matching RULES entry  -> first match wins
  4. DEFAULT_RULE
"""

from __future__ import annotations

import functools
import re
from typing import Any

from django.urls import Resolver404, resolve
from django.utils.module_loading import import_string

from tokenguard.budget import Budget
from tokenguard.django.conf import get_setting
from tokenguard.django.engine import Rule, add_headers, enforce, settle
from tokenguard.django.keys import resolve_key


@functools.lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def _resolve_callable(value: Any) -> Any:
    """Settings can name a function by dotted path: "myapp.costs.chat_cost"."""
    return import_string(value) if isinstance(value, str) else value


def rule_from_spec(spec: dict[str, Any], scope: str) -> Rule:
    budget = spec.get("budget")
    if isinstance(budget, dict):  # {"daily_tokens": 50_000, "monthly_usd": 20}
        budget = Budget(**budget)
    budget_key = spec.get("budget_key")
    return Rule(
        capacity=spec["capacity"],
        refill_rate=spec["refill_rate"],
        key=resolve_key(spec.get("key")),
        scope=scope,
        fail_mode=spec.get("fail_mode"),
        cost=_resolve_callable(spec.get("cost", 1)),
        usage=_resolve_callable(spec.get("usage")),
        budget=budget,
        budget_key=resolve_key(budget_key) if budget_key else None,
    )


class TokenGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rule = self.rule_for(request)
        if rule is None:
            return self.get_response(request)

        outcome = enforce(request, rule)
        if outcome.rejection is not None:
            return outcome.rejection
        response = self.get_response(request)
        # Django turns view exceptions into 500 responses before they reach us,
        # so settle() sees them as a 5xx and refunds.
        settle(request, rule, outcome.charge, response)
        if outcome.charge is not None:
            add_headers(response, rule, outcome.charge.remaining)
        return response

    @staticmethod
    def rule_for(request) -> Rule | None:
        path = request.path_info
        if any(_compile(p).match(path) for p in get_setting("EXEMPT")):
            return None

        try:
            view = resolve(path).func
        except Resolver404:
            view = None
        if view is not None and hasattr(view, "tokenguard_rule"):
            return None  # the decorator handles (and charges) this view

        for spec in get_setting("RULES"):
            if _compile(spec["match"]).match(path):
                return rule_from_spec(spec, scope=spec.get("name", spec["match"]))

        return rule_from_spec(get_setting("DEFAULT_RULE"), scope="default")
