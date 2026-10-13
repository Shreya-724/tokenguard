"""Budgets on top of the token bucket: burst + daily + monthly, charged atomically.

Three layers guard each client:
  burst    the token bucket (short spikes, refills continuously)
  daily    a counter that resets at 00:00 UTC
  monthly  a counter that resets on the 1st of the month, 00:00 UTC

All three are checked and charged by ONE Lua script, so a request is either
charged to every layer or to none, never half. Spend is also tracked in dollars.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tokenguard.bucket import validate_params
from tokenguard.clock import Clock
from tokenguard.errors import wrap_redis_errors

_HERE = Path(__file__).parent
_CHARGE_LUA = (_HERE / "token_bucket_budget.lua").read_text(encoding="utf-8")
_ADJUST_LUA = (_HERE / "token_bucket_budget_adjust.lua").read_text(encoding="utf-8")

DAY_TTL = 40 * 86_400  # keep daily totals about 40 days (reports, dashboards)
MONTH_TTL = 400 * 86_400  # and monthly totals about 13 months


@dataclass(frozen=True)
class Cost:
    """What one request is expected to consume."""

    tokens: float  # raw tokens: input + expected output
    dollars: float = 0.0  # estimated price
    weight: float = 1.0  # multiplies tokens for the burst bucket (expensive models)

    def __post_init__(self) -> None:
        if self.tokens < 0 or self.dollars < 0:
            raise ValueError("cost must be >= 0")
        if self.weight <= 0:
            raise ValueError("weight must be > 0")

    @property
    def burst(self) -> float:
        """What the burst bucket is charged: tokens x weight."""
        return self.tokens * self.weight


@dataclass(frozen=True)
class Usage:
    """What a request really consumed, as reported by the model."""

    tokens: float
    dollars: float | None = None  # None: keep the estimated dollars


@dataclass(frozen=True)
class Budget:
    """Daily and monthly caps. 0 means no cap on that metric."""

    daily_tokens: float = 0
    daily_usd: float = 0
    monthly_tokens: float = 0
    monthly_usd: float = 0
    near_limit: float = 0.8  # raise a "near limit" event at this fraction used

    def __post_init__(self) -> None:
        limits = (self.daily_tokens, self.daily_usd, self.monthly_tokens)
        if min(limits + (self.monthly_usd,)) < 0:
            raise ValueError("budget limits must be >= 0")
        if not 0 < self.near_limit <= 1:
            raise ValueError("near_limit must be in (0, 1]")


@dataclass(frozen=True)
class Spend:
    """Running totals for the current UTC day and month."""

    day_tokens: float = 0.0
    day_usd: float = 0.0
    month_tokens: float = 0.0
    month_usd: float = 0.0

    def minus(self, tokens: float, usd: float) -> Spend:
        return Spend(
            max(0.0, self.day_tokens - tokens),
            max(0.0, self.day_usd - usd),
            max(0.0, self.month_tokens - tokens),
            max(0.0, self.month_usd - usd),
        )


@dataclass(frozen=True)
class Periods:
    """Which UTC day and month a charge belongs to, and when they reset."""

    day: str  # "2026-10-13"
    month: str  # "2026-10"
    day_resets_in: float  # seconds until the next UTC midnight
    month_resets_in: float  # seconds until the 1st of next month, 00:00 UTC


def period_info(ts: float) -> Periods:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    midnight = dict(hour=0, minute=0, second=0, microsecond=0)
    next_day = (dt + timedelta(days=1)).replace(**midnight)
    if dt.month == 12:
        next_month = dt.replace(year=dt.year + 1, month=1, day=1, **midnight)
    else:
        next_month = dt.replace(month=dt.month + 1, day=1, **midnight)
    return Periods(
        day=dt.strftime("%Y-%m-%d"),
        month=dt.strftime("%Y-%m"),
        day_resets_in=(next_day - dt).total_seconds(),
        month_resets_in=(next_month - dt).total_seconds(),
    )


@dataclass(frozen=True)
class BudgetDecision:
    allowed: bool
    blocked_by: str | None  # None, "burst", "daily_tokens", "monthly_usd", ...
    remaining: float  # burst tokens left
    retry_after: float  # seconds until it could succeed (inf: never)
    spend: Spend
    periods: Periods


def near_limit_events(
    budget: Budget, before: Spend, after: Spend
) -> list[dict[str, Any]]:
    """Events for every cap that just crossed its near-limit threshold.

    Fires once per crossing (before < threshold <= after), so a client sitting
    at 90% does not raise an alert on every request.
    """
    layers = (
        ("daily", "tokens", budget.daily_tokens, before.day_tokens, after.day_tokens),
        ("daily", "usd", budget.daily_usd, before.day_usd, after.day_usd),
        (
            "monthly",
            "tokens",
            budget.monthly_tokens,
            before.month_tokens,
            after.month_tokens,
        ),
        ("monthly", "usd", budget.monthly_usd, before.month_usd, after.month_usd),
    )
    events = []
    for layer, metric, limit, was, now in layers:
        if limit > 0 and was < limit * budget.near_limit <= now:
            events.append(
                {
                    "layer": layer,
                    "metric": metric,
                    "used": now,
                    "limit": float(limit),
                    "fraction": now / limit,
                }
            )
    return events


class BudgetedBucket:
    """A burst bucket plus daily and monthly budgets, charged in one Lua call.

    budget_id  who owns the budgets (e.g. "chat:user:42"). It becomes the Redis
               hash tag {budget_id}, so all three keys hash to the same slot,
               which multi-key Lua needs on Redis Cluster.
    bucket_id  names the burst bucket within that owner, so one user can have a
               separate burst bucket per model but ONE budget across models.
    """

    def __init__(
        self,
        client: Any,
        budget_id: str,
        bucket_id: str,
        capacity: float,
        refill_rate: float,
        budget: Budget,
        clock: Clock | None = None,
        key_prefix: str = "tb:",
    ) -> None:
        validate_params(capacity, refill_rate)
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self.budget = budget
        self._clock = clock  # None -> real time (and Redis TIME for the bucket)
        tag = "{" + budget_id.replace("{", "_").replace("}", "_") + "}"
        self._base = f"{key_prefix}{tag}"
        self._bucket_key = f"{self._base}:bucket:{bucket_id}"
        self._charge_script = client.register_script(_CHARGE_LUA)
        self._adjust_script = client.register_script(_ADJUST_LUA)

    def _now(self) -> float:
        return self._clock.now() if self._clock is not None else time.time()

    def _now_arg(self) -> str:
        return "" if self._clock is None else repr(self._clock.now())

    def keys(self, periods: Periods) -> list[str]:
        return [
            self._bucket_key,
            f"{self._base}:day:{periods.day}",
            f"{self._base}:month:{periods.month}",
        ]

    def fits(self, cost: Cost) -> bool:
        """False if this request can NEVER be admitted, however long it waits."""
        b = self.budget
        if cost.burst > self.capacity:
            return False
        caps = (
            (b.daily_tokens, cost.tokens),
            (b.monthly_tokens, cost.tokens),
            (b.daily_usd, cost.dollars),
            (b.monthly_usd, cost.dollars),
        )
        return not any(0 < limit < amount for limit, amount in caps)

    @wrap_redis_errors
    def charge(self, cost: Cost) -> BudgetDecision:
        """Charge every layer, or none of them."""
        periods = period_info(self._now())
        b = self.budget
        allowed, blocked, burst, day_t, day_u, mon_t, mon_u, retry = (
            self._charge_script(
                keys=self.keys(periods),
                args=[
                    self.capacity,
                    self.refill_rate,
                    cost.burst,
                    self._now_arg(),
                    cost.tokens,
                    cost.dollars,
                    b.daily_tokens,
                    b.daily_usd,
                    b.monthly_tokens,
                    b.monthly_usd,
                    DAY_TTL,
                    MONTH_TTL,
                ],
            )
        )
        spend = Spend(float(day_t), float(day_u), float(mon_t), float(mon_u))
        if int(allowed):
            return BudgetDecision(True, None, float(burst), 0.0, spend, periods)
        blocked = blocked.decode() if isinstance(blocked, bytes) else blocked
        if blocked.startswith("daily"):
            retry_after = periods.day_resets_in
        elif blocked.startswith("monthly"):
            retry_after = periods.month_resets_in
        else:
            retry_after = float(retry)
        return BudgetDecision(False, blocked, float(burst), retry_after, spend, periods)

    @wrap_redis_errors
    def adjust(
        self,
        delta_burst: float,
        delta_tokens: float,
        delta_usd: float,
        periods: Periods,
    ) -> tuple[float, Spend]:
        """Settle an estimate: positive deltas charge more, negative refund.

        `periods` must be the ones returned when the charge was made, so a
        refund after midnight still goes to the day the charge was booked on.
        Returns (burst tokens left, new spend totals).
        """
        burst, day_t, day_u, mon_t, mon_u = self._adjust_script(
            keys=self.keys(periods),
            args=[
                self.capacity,
                self.refill_rate,
                delta_burst,
                self._now_arg(),
                delta_tokens,
                delta_usd,
                DAY_TTL,
                MONTH_TTL,
            ],
        )
        spend = Spend(float(day_t), float(day_u), float(mon_t), float(mon_u))
        return float(burst), spend
