"""Redis-backed token buckets: a naive (racy) one and an atomic Lua one."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from tokenguard.bucket import Decision, validate_cost, validate_params
from tokenguard.clock import Clock, WallClock
from tokenguard.errors import wrap_redis_errors

_HERE = Path(__file__).parent
_LUA = (_HERE / "token_bucket.lua").read_text(encoding="utf-8")
_ADJUST_LUA = (_HERE / "token_bucket_adjust.lua").read_text(encoding="utf-8")


def _ttl(capacity: float, refill_rate: float) -> int:
    # An idle bucket is full after capacity/refill_rate seconds; keep 2x that.
    return max(1, math.ceil(capacity / refill_rate) * 2)


class NaiveRedisTokenBucket:
    """Read -> compute in Python -> write back. NOT safe under concurrency.

    Kept on purpose, to demonstrate the check-then-act race condition.
    """

    def __init__(
        self,
        client: Any,
        key: str,
        capacity: float,
        refill_rate: float,
        clock: Clock | None = None,
        key_prefix: str = "tb:",
    ) -> None:
        validate_params(capacity, refill_rate)
        self._r = client
        self._key = f"{key_prefix}{key}"
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        # Wall clock, not monotonic: monotonic values differ between processes.
        self._clock: Clock = clock or WallClock()

    def _state(self, spend: bool, cost: float) -> Decision:
        now = self._clock.now()
        tokens_raw, ts_raw = self._r.hmget(self._key, "tokens", "ts")  # 1. READ
        if tokens_raw is None or ts_raw is None:
            tokens, ts = self.capacity, now
        else:
            tokens, ts = float(tokens_raw), float(ts_raw)

        elapsed = max(0.0, now - ts)  # 2. COMPUTE
        tokens = min(self.capacity, tokens + elapsed * self.refill_rate)

        allowed = cost <= tokens
        retry_after = 0.0
        if allowed:
            if spend:
                tokens -= cost
        elif cost > self.capacity:
            retry_after = math.inf
        else:
            retry_after = (cost - tokens) / self.refill_rate

        if spend:  # 3. WRITE (another client may have written since step 1!)
            self._r.hset(self._key, mapping={"tokens": repr(tokens), "ts": repr(now)})
            self._r.expire(self._key, _ttl(self.capacity, self.refill_rate))
        return Decision(allowed, tokens, retry_after)

    @wrap_redis_errors
    def allow(self, cost: float = 1) -> Decision:
        validate_cost(cost)
        return self._state(True, cost)

    @wrap_redis_errors
    def peek(self, cost: float = 1) -> Decision:
        validate_cost(cost)
        return self._state(False, cost)


class RedisTokenBucket:
    """Atomic token bucket: the whole read-compute-write runs inside Redis (Lua)."""

    def __init__(
        self,
        client: Any,
        key: str,
        capacity: float,
        refill_rate: float,
        clock: Clock | None = None,
        key_prefix: str = "tb:",
    ) -> None:
        validate_params(capacity, refill_rate)
        self._r = client
        self._key = f"{key_prefix}{key}"
        self.capacity = float(capacity)
        self.refill_rate = float(refill_rate)
        # clock=None -> Redis TIME (production). A clock is only for tests.
        self._clock = clock
        self._script = client.register_script(_LUA)
        self._adjust_script = client.register_script(_ADJUST_LUA)

    def _now_arg(self) -> str:
        return "" if self._clock is None else repr(self._clock.now())

    def _run(self, cost: float, spend: bool) -> Decision:
        allowed, tokens, retry_after = self._script(
            keys=[self._key],
            args=[
                self.capacity,
                self.refill_rate,
                cost,
                self._now_arg(),
                "1" if spend else "0",
            ],
        )
        return Decision(bool(int(allowed)), float(tokens), float(retry_after))

    @wrap_redis_errors
    def allow(self, cost: float = 1) -> Decision:
        validate_cost(cost)
        return self._run(cost, True)

    @wrap_redis_errors
    def peek(self, cost: float = 1) -> Decision:
        validate_cost(cost)
        return self._run(cost, False)

    @wrap_redis_errors
    def adjust(self, delta: float) -> float:
        """Atomically charge (delta > 0) or refund (delta < 0). Returns the balance.

        Same debt rules as TokenBucket.adjust: balance stays within
        [-capacity, capacity].
        """
        result = self._adjust_script(
            keys=[self._key],
            args=[self.capacity, self.refill_rate, delta, self._now_arg()],
        )
        return float(result)
