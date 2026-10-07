from tokenguard.clock import SystemClock

class TokenBucket:
    def __init__(self, capacity, refill_rate, clock=None):
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        if refill_rate <= 0:
            raise ValueError("refill_rate must be > 0")
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._clock = clock or SystemClock()
        self.tokens = capacity
        self.last_refill = self._clock.now()

    def allow(self, cost=1):
    # Decision: negative cost is a caller bug, not a refund.
        if cost < 0:
         raise ValueError("cost must be >= 0")
        now = self._clock.now()
    # Decision: if the clock goes backwards, add nothing (never negative).
        elapsed = max(0.0, now - self.last_refill)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    # Decision: cost > capacity naturally fails (tokens can never reach it).
    # Decision: cost == 0 is always allowed and spends nothing.
        if self.tokens >= cost:
         self.tokens -= cost
         return True
        return False