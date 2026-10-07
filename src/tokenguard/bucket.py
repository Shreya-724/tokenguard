from tokenguard.clock import SystemClock

class TokenBucket:
    def __init__(self, capacity, refill_rate, clock=None):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._clock = clock or SystemClock()
        self.tokens = capacity
        self.last_refill = self._clock.now()

    def allow(self, cost=1):
        now = self._clock.now()          # was time.monotonic()
        # ... rest unchanged