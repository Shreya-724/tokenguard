"""What the staff-only REST API does, without any web framework in sight.

Each function takes plain values and returns plain dicts (or raises ApiError),
so it can be tested directly and the views stay thin.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import redis

from tokenguard.algorithms import Limit
from tokenguard.dashboard import snapshot
from tokenguard.django.catalog import known_rules
from tokenguard.django.conf import (
    get_metrics_reader,
    get_rule_store,
    get_setting,
)
from tokenguard.django.engine import Rule, effective_rule
from tokenguard.errors import RedisUnavailableError
from tokenguard.rulestore import validate_override

REDIS_DOWN = (redis.RedisError, RedisUnavailableError)
RULE_FIELDS = ("capacity", "refill_rate", "algorithm")


class ApiError(Exception):
    """An error with an HTTP status, shown to the caller as {"error": message}."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def redis_unavailable() -> ApiError:
    return ApiError(503, "Redis is unavailable")


# ---- stats and consumers ----
def stats(seconds: int = 60, step: int = 1, n: int = 5, minutes: int = 2):
    try:
        return snapshot(
            get_metrics_reader(), seconds=seconds, step=step, n=n, minutes=minutes
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from None
    except REDIS_DOWN:
        raise redis_unavailable() from None


def consumers(n: int = 10, minutes: int = 5, by: str = "tokens"):
    try:
        rows = get_metrics_reader().top_consumers(n=n, minutes=minutes, by=by)
    except ValueError as exc:
        raise ApiError(400, str(exc)) from None
    except REDIS_DOWN:
        raise redis_unavailable() from None
    return {"by": by, "minutes": minutes, "consumers": [c.as_dict() for c in rows]}


# ---- rules ----
def _algorithm_of(rule: Rule) -> str:
    return rule.algorithm or get_setting("ALGORITHM")


def _describe(
    scope: str, source: str, rule: Rule, override: Any, live: bool
) -> dict[str, Any]:
    applied = effective_rule(rule) if live else rule
    return {
        "scope": scope,
        "source": source,
        "budget": rule.budget is not None,
        "configured": {
            "capacity": rule.capacity,
            "refill_rate": rule.refill_rate,
            "algorithm": _algorithm_of(rule),
        },
        "override": (
            None
            if override is None
            else {name: getattr(override, name) for name in RULE_FIELDS}
        ),
        "effective": {
            "capacity": applied.capacity,
            "refill_rate": applied.refill_rate,
            "algorithm": _algorithm_of(applied),
        },
    }


def list_rules() -> dict[str, Any]:
    live = bool(get_setting("LIVE_RULES"))
    try:
        rules = get_rule_store().refresh()  # an admin screen wants fresh data
        items = [
            _describe(scope, source, rule, rules.overrides.get(scope), live)
            for scope, (source, rule) in known_rules().items()
        ]
    except REDIS_DOWN:
        raise redis_unavailable() from None
    return {
        "live_rules_enabled": live,
        "version": rules.version,
        "ttl": float(get_setting("LIVE_RULES_TTL")),  # seconds until servers notice
        "rules": items,
    }


def _find(scope: str) -> tuple[str, Rule]:
    try:
        return known_rules()[scope]
    except KeyError:
        raise ApiError(404, f"no rule named {scope!r}") from None


def get_rule(scope: str) -> dict[str, Any]:
    _find(scope)
    return next(r for r in list_rules()["rules"] if r["scope"] == scope)


def update_rule(scope: str, data: Any) -> dict[str, Any]:
    """Replace the live override for a rule (what you send is the whole override)."""
    _, rule = _find(scope)
    if not isinstance(data, dict):
        raise ApiError(400, "send a JSON object")
    unknown = sorted(set(data) - set(RULE_FIELDS))
    if unknown:
        raise ApiError(400, f"unknown field(s) {unknown}; allowed: {list(RULE_FIELDS)}")
    try:
        override = validate_override(
            data.get("capacity"), data.get("refill_rate"), data.get("algorithm")
        )
        # The same check the engine makes, so a bad combination is refused here
        # instead of being silently ignored at request time.
        dataclasses.replace(
            rule,
            **{n: getattr(override, n) for n in RULE_FIELDS if getattr(override, n)},
        )
    except ValueError as exc:
        raise ApiError(400, str(exc)) from None
    try:
        get_rule_store().set_rule(
            scope, override.capacity, override.refill_rate, override.algorithm
        )
    except REDIS_DOWN:
        raise redis_unavailable() from None
    return get_rule(scope)


def reset_rule(scope: str) -> dict[str, Any]:
    """Remove the override, so the rule goes back to what the settings say."""
    _find(scope)
    try:
        get_rule_store().delete_rule(scope)
    except REDIS_DOWN:
        raise redis_unavailable() from None
    return get_rule(scope)


# ---- one bucket ----
def bucket(key: str) -> dict[str, Any]:
    """How much of its limit `scope:identity` has left, without spending any."""
    rules = known_rules()
    matches = [s for s in rules if key.startswith(f"{s}:") and len(key) > len(s) + 1]
    if not matches:
        raise ApiError(404, "no known rule matches this key; keys look like scope:id")
    scope = max(matches, key=len)  # "api" vs "api:v2": the most specific wins
    identity = key[len(scope) + 1 :]
    rule = effective_rule(rules[scope][1])
    if rule.budget is not None:
        raise ApiError(422, "bucket levels for budgeted rules are not available yet")
    algorithm = _algorithm_of(rule)
    try:
        level = get_metrics_reader().bucket_level(
            scope,
            identity,
            Limit(rule.capacity, rule.refill_rate),
            algorithm=algorithm,
            key_prefix=f"{get_setting('KEY_PREFIX')}:",
        )
    except REDIS_DOWN:
        raise redis_unavailable() from None
    return {**level.as_dict(), "scope": scope, "identity": identity}
