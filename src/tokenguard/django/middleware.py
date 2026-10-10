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

from tokenguard.django.conf import get_setting
from tokenguard.django.engine import Rule, add_headers, enforce
from tokenguard.django.keys import resolve_key


@functools.lru_cache(maxsize=256)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def rule_from_spec(spec: dict[str, Any], scope: str) -> Rule:
    return Rule(
        capacity=spec["capacity"],
        refill_rate=spec["refill_rate"],
        key=resolve_key(spec.get("key")),
        scope=scope,
        fail_mode=spec.get("fail_mode"),
        cost=spec.get("cost", 1),
    )


class TokenGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rule = self.rule_for(request)
        if rule is None:
            return self.get_response(request)

        decision, rejection = enforce(request, rule)
        if rejection is not None:
            return rejection
        response = self.get_response(request)
        if decision is not None:
            add_headers(response, rule, decision)
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
