"""Rate-limit algorithms behind one interface.

    algorithm = get_algorithm("fixed_window", redis_client)
    rule = Limit(capacity=60, refill_rate=1)
    decision = algorithm.check("user:42", 1, rule)

Every algorithm answers the same question: may `key` spend `cost` now, under
this rule? The rule is the same two numbers everywhere: `capacity` is the most
that can be spent at once, and `refill_rate` the sustained units per second.
Window algorithms read that as "`capacity` units per `capacity / refill_rate`
seconds", so switching algorithm never changes the long-run average.

    token_bucket  smooth refill, allows bursts up to capacity   (the default)
    fixed_window  a counter that resets every window; cheapest, but a client
                  can use two windows' worth around a window edge
    sliding_window  a log of recent requests; exact (no edge burst), but it
                  stores one entry per request in the window
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from tokenguard.bucket import Decision, validate_cost, validate_params
from tokenguard.clock import Clock
from tokenguard.errors import wrap_redis_errors
from tokenguard.redis_bucket import RedisTokenBucket

_HERE = Path(__file__).parent
_FIXED_WINDOW_LUA = (_HERE / "fixed_window.lua").read_text(encoding="utf-8")
_FIXED_WINDOW_ADJUST_LUA = (_HERE / "fixed_window_adjust.lua").read_text(
    encoding="utf-8"
)
_SLIDING_WINDOW_LUA = (_HERE / "sliding_window.lua").read_text(encoding="utf-8")
_SLIDING_WINDOW_ADJUST_LUA = (_HERE / "sliding_window_adjust.lua").read_text(
    encoding="utf-8"
)


@dataclass(frozen=True)
class Limit:
    """What to enforce: `capacity` at once, `refill_rate` per second sustained."""

    capacity: float
    refill_rate: float

    def __post_init__(self) -> None:
        validate_params(self.capacity, self.refill_rate)

    @property
    def window(self) -> float:
        """Seconds one capacity-worth takes to refill (a window algorithm's size)."""
        return self.capacity / self.refill_rate


class Algorithm(Protocol):
    """What the rest of tokenguard needs from a rate-limit algorithm."""

    name: str

    def check(self, key: str, cost: float, rule: Limit) -> Decision:
        """Spend `cost` if it fits, and say whether it did."""

    def peek(self, key: str, cost: float, rule: Limit) -> Decision:
        """The answer check() would give, without spending anything."""

    def adjust(self, key: str, delta: float, rule: Limit) -> float:
        """Settle an estimate: charge (delta > 0) or refund (delta < 0).

        Returns the units left."""


class TokenBucketAlgorithm:
    """The Week 2 token bucket (atomic Lua), behind the common interface."""

    name = "token_bucket"

    def __init__(
        self, client: Any, clock: Clock | None = None, key_prefix: str = "tb:"
    ) -> None:
        self._r = client
        self._clock = clock
        self._prefix = key_prefix

    def _bucket(self, key: str, rule: Limit) -> RedisTokenBucket:
        return RedisTokenBucket(
            self._r,
            key,
            rule.capacity,
            rule.refill_rate,
            clock=self._clock,
            key_prefix=self._prefix,
        )

    def check(self, key: str, cost: float, rule: Limit) -> Decision:
        return self._bucket(key, rule).allow(cost)

    def peek(self, key: str, cost: float, rule: Limit) -> Decision:
        return self._bucket(key, rule).peek(cost)

    def adjust(self, key: str, delta: float, rule: Limit) -> float:
        return self._bucket(key, rule).adjust(delta)


class FixedWindowAlgorithm:
    """A counter per window (Lua, atomic). Cheap, with the boundary problem.

    Time is cut into windows of `rule.window` seconds. A key may spend up to
    `rule.capacity` in each window, and the counter starts again at zero when a
    new window begins. So a client can spend a full quota just before a window
    ends and another just after it starts: up to twice the limit in a short span.
    """

    name = "fixed_window"

    def __init__(
        self, client: Any, clock: Clock | None = None, key_prefix: str = "tb:"
    ) -> None:
        self._r = client
        self._clock = clock  # None -> Redis TIME (production); a clock is for tests
        self._prefix = key_prefix
        self._script = client.register_script(_FIXED_WINDOW_LUA)
        self._adjust_script = client.register_script(_FIXED_WINDOW_ADJUST_LUA)

    def _key(self, key: str) -> str:
        # Namespaced, so the same key under another algorithm never collides.
        return f"{self._prefix}fw:{key}"

    def _now_arg(self) -> str:
        return "" if self._clock is None else repr(self._clock.now())

    def _run(self, key: str, cost: float, rule: Limit, spend: bool) -> Decision:
        validate_cost(cost)
        allowed, remaining, retry_after, reset_after = self._script(
            keys=[self._key(key)],
            args=[
                rule.capacity,
                rule.window,
                cost,
                self._now_arg(),
                "1" if spend else "0",
            ],
        )
        return Decision(
            bool(int(allowed)),
            float(remaining),
            float(retry_after),
            float(reset_after),
        )

    @wrap_redis_errors
    def check(self, key: str, cost: float, rule: Limit) -> Decision:
        return self._run(key, cost, rule, True)

    @wrap_redis_errors
    def peek(self, key: str, cost: float, rule: Limit) -> Decision:
        return self._run(key, cost, rule, False)

    @wrap_redis_errors
    def adjust(self, key: str, delta: float, rule: Limit) -> float:
        result = self._adjust_script(
            keys=[self._key(key)],
            args=[rule.capacity, rule.window, delta, self._now_arg()],
        )
        return float(result)


class SlidingWindowAlgorithm:
    """A sliding-window LOG (sorted set + Lua): exact, at the price of memory.

    At most `rule.capacity` units may be spent in ANY span of `rule.window`
    seconds, not just in each clock-aligned window. Every spending request adds
    one entry (its time, and its cost) to a sorted set; entries older than the
    window are ignored and cleaned up, and the live costs are summed. So there is
    no edge to exploit, and `retry_after` is exact: the moment enough old
    entries have expired.

    Why a log and not the cheaper sliding-window counter: the counter assumes
    traffic was spread evenly through the previous window, and a burst packed at
    the end of a window can still slip almost a second window's worth through.
    The log has no such gap. Its cost is one entry per request in the window,
    which is small for LLM traffic (few, expensive requests per key), and a
    request costing 5,000 tokens is still one entry.
    """

    name = "sliding_window"

    def __init__(
        self, client: Any, clock: Clock | None = None, key_prefix: str = "tb:"
    ) -> None:
        self._r = client
        self._clock = clock
        self._prefix = key_prefix
        self._script = client.register_script(_SLIDING_WINDOW_LUA)
        self._adjust_script = client.register_script(_SLIDING_WINDOW_ADJUST_LUA)

    def _key(self, key: str) -> str:
        return f"{self._prefix}sw:{key}"

    def _now_arg(self) -> str:
        return "" if self._clock is None else repr(self._clock.now())

    def _run(self, key: str, cost: float, rule: Limit, spend: bool) -> Decision:
        validate_cost(cost)
        allowed, remaining, retry_after, reset_after = self._script(
            keys=[self._key(key)],
            args=[
                rule.capacity,
                rule.window,
                cost,
                self._now_arg(),
                "1" if spend else "0",
                uuid.uuid4().hex,  # entries in a sorted set must be unique
            ],
        )
        return Decision(
            bool(int(allowed)),
            float(remaining),
            float(retry_after),
            float(reset_after),
        )

    @wrap_redis_errors
    def check(self, key: str, cost: float, rule: Limit) -> Decision:
        return self._run(key, cost, rule, True)

    @wrap_redis_errors
    def peek(self, key: str, cost: float, rule: Limit) -> Decision:
        return self._run(key, cost, rule, False)

    @wrap_redis_errors
    def adjust(self, key: str, delta: float, rule: Limit) -> float:
        result = self._adjust_script(
            keys=[self._key(key)],
            args=[
                rule.capacity,
                rule.window,
                delta,
                self._now_arg(),
                uuid.uuid4().hex,
            ],
        )
        return float(result)


AlgorithmFactory = Callable[..., Algorithm]

_FACTORIES: dict[str, AlgorithmFactory] = {
    "token_bucket": TokenBucketAlgorithm,
    "fixed_window": FixedWindowAlgorithm,
    "sliding_window": SlidingWindowAlgorithm,
}


def register_algorithm(name: str, factory: AlgorithmFactory) -> None:
    """Add an algorithm. `factory(client, clock=None, key_prefix=...)` builds it."""
    _FACTORIES[name] = factory


def algorithm_names() -> tuple[str, ...]:
    return tuple(_FACTORIES)


def get_algorithm(
    name: str, client: Any, clock: Clock | None = None, key_prefix: str = "tb:"
) -> Algorithm:
    """Build an algorithm by name (this is what the Django settings use)."""
    try:
        factory = _FACTORIES[name]
    except KeyError:
        known = ", ".join(algorithm_names())
        raise ValueError(f"unknown algorithm {name!r}; known: {known}") from None
    return factory(client, clock=clock, key_prefix=key_prefix)
