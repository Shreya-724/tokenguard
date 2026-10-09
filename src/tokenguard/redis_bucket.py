"""Redis-backed token buckets: a naive (racy) one and an atomic Lua one."""

from __future__ import annotations

import math
from typing import Any
from pathlib import Path
from tokenguard.bucket import Decision, validate_cost, validate_params
from tokenguard.clock import Clock, WallClock
from tokenguard.errors import wrap_redis_errors

_LUA = (Path(__file__).with_name("token_bucket.lua")).read_text()


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

    def _run(self, cost: float, spend: bool) -> Decision:
        now = "" if self._clock is None else repr(self._clock.now())
        allowed, tokens, retry_after = self._script(
            keys=[self._key],
            args=[self.capacity, self.refill_rate, cost, now, "1" if spend else "0"],
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