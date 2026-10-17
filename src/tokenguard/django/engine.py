"""Shared logic used by both the decorator and the middleware."""

from __future__ import annotations

import dataclasses
import functools
import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.http import HttpResponse, JsonResponse
from django.utils.module_loading import import_string

from tokenguard.algorithms import Algorithm, Limit, algorithm_names, get_algorithm
from tokenguard.bucket import Decision
from tokenguard.budget import (
    Budget,
    BudgetDecision,
    BudgetedBucket,
    Cost,
    Spend,
    Usage,
    near_limit_events,
)
from tokenguard.django.conf import (
    check_algorithm,
    check_fail_mode,
    get_client,
    get_rule_store,
    get_setting,
)
from tokenguard.django.keys import KeyFunc
from tokenguard.errors import RedisUnavailableError

logger = logging.getLogger("tokenguard")

# request -> tokens (a number) or a Cost with dollars and a model weight
CostFunc = Callable[[Any], "float | Cost"]
# (request, response) -> tokens really used (a number), a Usage, or None
UsageFunc = Callable[[Any, Any], "float | Usage | None"]


@dataclass(frozen=True)
class Rule:
    capacity: float
    refill_rate: float
    key: KeyFunc
    scope: str  # namespaces the bucket so different rules never share one
    fail_mode: str | None = None  # None -> the global FAIL_MODE setting
    cost: float | Cost | CostFunc = 1  # a number, a Cost, or a function of the request
    usage: UsageFunc | None = None  # real usage, to settle the estimate afterwards
    budget: Budget | None = None  # daily / monthly caps on top of the burst bucket
    budget_key: KeyFunc | None = None  # who owns the budget (default: same as key)
    algorithm: str | None = None  # None -> the global ALGORITHM setting
    rules_version: int | None = None  # set when live rules are on: their version

    def __post_init__(self) -> None:
        if self.algorithm is not None and self.algorithm not in algorithm_names():
            raise ValueError(
                f"unknown algorithm {self.algorithm!r}; "
                f"choose one of {algorithm_names()}"
            )
        if self.budget is not None and self.algorithm not in (None, "token_bucket"):
            raise ValueError(
                "budgets are built on the token bucket; "
                f"algorithm={self.algorithm!r} cannot be combined with a budget"
            )

    def cost_for(self, request: Any) -> Cost:
        value = self.cost(request) if callable(self.cost) else self.cost
        return value if isinstance(value, Cost) else Cost(float(value))


def _notify_near_limit(rule: Rule, identity: str, before: Spend, after: Spend) -> None:
    events = near_limit_events(rule.budget, before, after) if rule.budget else []
    if not events:
        return
    hook = get_setting("ON_NEAR_LIMIT")
    if isinstance(hook, str):
        hook = import_string(hook)
    for event in events:
        event = {"scope": rule.scope, "identity": identity, **event}
        logger.warning("tokenguard near limit: %s", event)
        if hook is None:
            continue
        try:
            hook(event)
        except Exception:
            logger.exception("ON_NEAR_LIMIT hook failed")


class Charge:
    """What a request was charged up front, so it can be settled afterwards.

    Available to views as `request.tokenguard`:
        request.tokenguard.reconcile(actual_tokens)     # or a Usage(tokens, usd)
    Only the first settlement counts, so calling it twice is harmless.
    Amounts are raw tokens; the model weight is applied for you.
    """

    def __init__(
        self,
        bucket: Any,
        cost: Cost,
        remaining: float,
        rule: Rule,
        identity: str,
        decision: BudgetDecision | None = None,
        reset_after: float | None = None,
    ):
        self._bucket = bucket
        self.cost = cost
        self.remaining = remaining
        self.reset_after = reset_after  # None: derived from the refill rate
        self.settled = False
        self._finalized = False
        self._rule = rule
        self._identity = identity
        self._periods = decision.periods if decision else None
        self.spend = decision.spend if decision else None
        self._spend_before = (
            decision.spend.minus(cost.tokens, cost.dollars) if decision else None
        )

    def reconcile(self, actual: float | Usage) -> float:
        """Replace the estimate with real usage. Returns the burst tokens left."""
        if self.settled:
            return self.remaining
        self.settled = True
        usage = actual if isinstance(actual, Usage) else Usage(float(actual))
        tokens = max(0.0, usage.tokens)
        d_burst = tokens * self.cost.weight - self.cost.burst  # >0 charge, <0 refund
        try:
            if self._periods is None:
                if d_burst != 0:
                    self.remaining = self._bucket.adjust(d_burst)
            else:
                d_tokens = tokens - self.cost.tokens
                d_usd = 0.0
                if usage.dollars is not None:
                    d_usd = max(0.0, usage.dollars) - self.cost.dollars
                if d_burst or d_tokens or d_usd:
                    self.remaining, self.spend = self._bucket.adjust(
                        d_burst, d_tokens, d_usd, self._periods
                    )
        except RedisUnavailableError as exc:
            # The work is already done; never fail the response over bookkeeping.
            logger.warning("Redis unavailable, could not reconcile usage: %s", exc)
        return self.remaining

    def refund(self) -> float:
        """The request failed: give back everything it was charged."""
        return self.reconcile(Usage(0.0, 0.0))

    def finalize(self) -> None:
        """Request over: raise near-limit alerts based on the FINAL numbers.

        Doing this after settlement avoids false alarms from a pessimistic
        estimate that was refunded a moment later.
        """
        if self._finalized or self._spend_before is None or self.spend is None:
            return
        self._finalized = True
        _notify_near_limit(self._rule, self._identity, self._spend_before, self.spend)


@dataclass
class Outcome:
    rejection: HttpResponse | None = None  # a ready 413/429/503, or None to proceed
    charge: Charge | None = None  # None if rejected, or Redis was down (fail-open)
    rule: Rule | None = None  # the rule actually applied (live changes included)


def _num(value: float) -> float | int:
    return int(value) if float(value).is_integer() else value


def add_headers(
    response: HttpResponse,
    rule: Rule,
    remaining: float,
    reset_after: float | None = None,
) -> None:
    """X-RateLimit-* headers (about the burst limit, in weighted tokens).

    Reset = unix time when the limit is full again. A fixed window knows that
    (its window ends); for a token bucket it is worked out from the refill rate.
    """
    if reset_after is None:
        reset_after = max(0.0, rule.capacity - remaining) / rule.refill_rate
    response["X-RateLimit-Limit"] = str(int(rule.capacity))
    response["X-RateLimit-Remaining"] = str(max(0, math.floor(remaining)))
    response["X-RateLimit-Reset"] = str(math.ceil(time.time() + reset_after))
    if rule.rules_version is not None:
        response["X-TokenGuard-Rules-Version"] = str(rule.rules_version)


def too_many_requests(rule: Rule, decision: Decision | BudgetDecision) -> HttpResponse:
    """429. Either the burst bucket is empty, or a daily/monthly budget is spent."""
    blocked = getattr(decision, "blocked_by", None)
    if blocked and blocked != "burst":
        body = {
            "error": "budget_exceeded",
            "limit": blocked,  # e.g. "daily_tokens", "monthly_usd"
            "retry_after": round(decision.retry_after),
        }
    else:
        body = {"error": "rate_limited", "retry_after": round(decision.retry_after, 3)}
    response = JsonResponse(body, status=429)
    response["Retry-After"] = str(math.ceil(decision.retry_after))
    add_headers(
        response, rule, decision.remaining, getattr(decision, "reset_after", None)
    )
    return response


def request_too_large(rule: Rule, cost: Cost) -> HttpResponse:
    """413: this single request costs more than a limit can ever hold.

    Not a 429 and no Retry-After: waiting will never make it fit. The caller
    has to send a smaller request (shorter prompt or lower max_tokens).
    """
    shown = cost.burst if cost.burst > rule.capacity else cost.tokens
    response = JsonResponse(
        {
            "error": "request_too_large",
            "cost": _num(shown),
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


@functools.lru_cache(maxsize=32)
def _algorithm(name: str, client: Any, prefix: str) -> Algorithm:
    """One algorithm object per (name, client, prefix), so scripts load once."""
    return get_algorithm(name, client, key_prefix=prefix)


class _Bound:
    """An algorithm bound to one key and limit, shaped like a bucket.

    Gives Charge the allow() and adjust() calls it needs, whichever algorithm
    sits underneath.
    """

    def __init__(self, algorithm: Algorithm, key: str, limit: Limit):
        self._algorithm = algorithm
        self._key = key
        self._limit = limit

    def allow(self, cost: float) -> Decision:
        return self._algorithm.check(self._key, cost, self._limit)

    def adjust(self, delta: float) -> float:
        return self._algorithm.adjust(self._key, delta, self._limit)


def _never_fits(rule: Rule, cost: Cost) -> bool:
    if cost.burst > rule.capacity:
        return True
    b = rule.budget
    if b is None:
        return False
    caps = (
        (b.daily_tokens, cost.tokens),
        (b.monthly_tokens, cost.tokens),
        (b.daily_usd, cost.dollars),
        (b.monthly_usd, cost.dollars),
    )
    return any(0 < limit < amount for limit, amount in caps)


def _effective_rule(rule: Rule) -> Rule:
    """The rule with any live override applied (a no-op unless LIVE_RULES)."""
    if not get_setting("LIVE_RULES"):
        return rule
    try:
        rules = get_rule_store().snapshot()
    except Exception:  # live rules must never take the limiter down
        logger.exception("tokenguard: live rules failed; using the configured rule")
        return rule
    changes: dict[str, Any] = {}
    if rules.loaded:
        changes["rules_version"] = rules.version
    override = rules.overrides.get(rule.scope)
    if override is not None:
        for name in ("capacity", "refill_rate", "algorithm"):
            value = getattr(override, name)
            if value is not None:
                changes[name] = value
    try:
        return dataclasses.replace(rule, **changes)
    except ValueError as exc:  # e.g. a fixed window asked for on a budgeted rule
        logger.warning("tokenguard: ignoring live rule for %r: %s", rule.scope, exc)
        return dataclasses.replace(rule, rules_version=changes.get("rules_version"))


def enforce(request: Any, rule: Rule) -> Outcome:
    """Charge the request against its bucket (before the view runs).

    The returned Outcome carries the rule that was really applied, which differs
    from `rule` when a live change is in effect: use it for headers and settling.
    """
    rule = _effective_rule(rule)
    outcome = _enforce(request, rule)
    outcome.rule = rule
    return outcome


def _enforce(request: Any, rule: Rule) -> Outcome:
    fail_mode = rule.fail_mode or get_setting("FAIL_MODE")
    check_fail_mode(fail_mode)

    cost = rule.cost_for(request)
    if _never_fits(rule, cost):
        # Decided locally: it can never fit, so it is rejected even if Redis is down.
        return Outcome(rejection=request_too_large(rule, cost))

    identity = rule.key(request)
    prefix = f"{get_setting('KEY_PREFIX')}:"
    budget_identity = ""
    if rule.budget is None:
        name = rule.algorithm or get_setting("ALGORITHM")
        check_algorithm(name)
        bucket: Any = _Bound(
            _algorithm(name, get_client(), prefix),
            f"{rule.scope}:{identity}",
            Limit(rule.capacity, rule.refill_rate),
        )
    else:
        owner = rule.budget_key(request) if rule.budget_key else identity
        budget_identity = f"{rule.scope}:{owner}"
        bucket = BudgetedBucket(
            get_client(),
            budget_identity,
            identity,
            rule.capacity,
            rule.refill_rate,
            rule.budget,
            key_prefix=prefix,
        )

    try:
        if rule.budget is None:
            decision = bucket.allow(cost.burst)
        else:
            decision = bucket.charge(cost)
    except RedisUnavailableError as exc:
        if fail_mode == "open":
            logger.warning("Redis unavailable, failing OPEN (%s): %s", rule.scope, exc)
            return Outcome()
        logger.error("Redis unavailable, failing CLOSED (%s): %s", rule.scope, exc)
        return Outcome(rejection=unavailable_response())

    if not decision.allowed:
        return Outcome(rejection=too_many_requests(rule, decision))

    charge = Charge(
        bucket,
        cost,
        decision.remaining,
        rule,
        budget_identity,
        decision if rule.budget is not None else None,
        getattr(decision, "reset_after", None),
    )
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
    if charge is None:
        return
    if not charge.settled:
        if response is None or response.status_code >= 500:
            charge.refund()
        elif rule.usage is not None:
            try:
                actual = rule.usage(request, response)
            except Exception:
                logger.exception("tokenguard usage function failed; keeping estimate")
                actual = None
            if actual is not None:
                charge.reconcile(actual)
    charge.finalize()
