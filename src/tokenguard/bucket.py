"""In-memory token bucket rate limiter."""

from __future__ import annotations

import math
from dataclasses import dataclass

from tokenguard.clock import Clock, SystemClock


@dataclass(frozen=True)
class Decision:
    """Result of a rate-limit check."""

    allowed: bool
    remaining: float
    retry_after: float  # seconds until enough tokens exist (inf if never)


def validate_params(capacity: float, refill_rate: float) -> None:
    if capacity <= 0:
        raise ValueError("capacity must be > 0")
    if refill_rate <= 0:
        raise ValueError("refill_rate must be > 0")


def validate_cost(cost: float) -> None:
    # Decision: negative cost is a caller bug, not a refund.
    if cost < 0:
        raise ValueError("cost must be >= 0")


class TokenBucket:
    """Holds up to `capacity` tokens, refilling at `refill_rate` tokens/second.

    Each request spends `cost` tokens; if there aren't enough it is rejected.
    """

    def __init__(
        self,
        capacity: float,
        refill_rate: float,
        clock: Clock | None = None,
    ) -> None:
        validate_params(capacity, refill_rate)
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        self._clock: Clock = clock or SystemClock()
        self._tokens = self.capacity
        self._last_refill = self._clock.now()

    def _refill(self) -> None:
        now = self._clock.now()
        # Decision: clock going backwards adds nothing (never negative).
        elapsed = max(0.0, now - self._last_refill)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now

    def _retry_after(self, cost: float) -> float:
        # Decision: a cost above capacity can never succeed.
        if cost > self.capacity:
            return math.inf
        return max(0.0, (cost - self._tokens) / self.refill_rate)

    def allow(self, cost: float = 1) -> Decision:
        """Try to spend `cost` tokens and return a Decision."""
        validate_cost(cost)
        self._refill()
        if cost <= self._tokens:  # cost == 0 is allowed and spends nothing
            self._tokens -= cost
            return Decision(True, self._tokens, 0.0)
        return Decision(False, self._tokens, self._retry_after(cost))

    def peek(self, cost: float = 1) -> Decision:
        """Report what allow(cost) would say, without spending anything."""
        validate_cost(cost)
        self._refill()
        if cost <= self._tokens:
            return Decision(True, self._tokens, 0.0)
        return Decision(False, self._tokens, self._retry_after(cost))
