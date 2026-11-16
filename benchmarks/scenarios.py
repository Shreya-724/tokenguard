"""Demo traffic for the tokenguard dashboard. Not for benchmarking.

benchmarks/locustfile.py is the measurement file: closed loop, fixed keys, so
its numbers stay comparable between runs. Leave that one alone. This file is
for watching the dashboard do something different each time.

Point it at an endpoint whose rule is small enough to be hit, for example a
rule you made in the dashboard rule editor (capacity 20, refill 5 per second):

    set DEMO_PATH=/demo/            (PowerShell: $env:DEMO_PATH = "/demo/")
    locust -f benchmarks/scenarios.py --headless -u 30 -r 10 -t 60s \
        --host http://127.0.0.1:8000 SteadyUser

Pick a scenario by class name. Name several to mix them:

    SteadyUser                    polite traffic, mostly allowed
    BurstyUser                    quiet, then a burst of requests, then quiet
    AbuserUser                    one key hammers the endpoint
    SteadyUser AbuserUser         normal callers plus one abuser (the mixed case)
    ManyKeysUser                  a fresh caller on most requests

Optional environment variables:

    DEMO_PATH   endpoint to call (default /demo/)
    SHAPE       spike | ramp | wave: also changes the number of users over time.
                When set, the run follows that shape and ignores -u/-r.
    SEED        any integer: same random traffic every run (for a demo video).
                Leave it unset to get different traffic every run.

A 429 is the limiter doing its job, so it counts as a success.
"""

import math
import os
import random
import uuid

from locust import FastHttpUser, LoadTestShape, between, constant, task

PATH = os.getenv("DEMO_PATH", "/demo/")

if os.getenv("SEED"):
    random.seed(int(os.environ["SEED"]))


def _get(user, api_key):
    with user.client.get(
        PATH, headers={"X-API-Key": api_key}, catch_response=True
    ) as response:
        if response.status_code in (200, 429):
            response.success()
        else:
            response.failure(f"HTTP {response.status_code}")


def _skewed_caller(pool=200):
    """A few heavy callers, a long tail of light ones (Pareto)."""
    return f"user-{min(int(random.paretovariate(1.2)), pool)}"


class SteadyUser(FastHttpUser):
    """Polite traffic: random pauses, skewed callers. Mostly 200s."""

    wait_time = between(0.3, 1.5)

    @task
    def hit(self):
        _get(self, _skewed_caller())


class BurstyUser(FastHttpUser):
    """Quiet for a while, then a quick burst from the same caller."""

    wait_time = between(1, 4)

    def on_start(self):
        self.caller = _skewed_caller()

    @task
    def burst(self):
        for _ in range(random.randint(5, 40)):
            _get(self, self.caller)


class AbuserUser(FastHttpUser):
    """One key sends as fast as it can. The dashboard should show it blocked."""

    wait_time = constant(0.02)

    @task
    def hit(self):
        _get(self, "abuser")


class ManyKeysUser(FastHttpUser):
    """Mostly brand-new callers, a few repeats. Stresses key count."""

    wait_time = between(0.05, 0.3)

    @task
    def hit(self):
        key = uuid.uuid4().hex if random.random() < 0.8 else _skewed_caller(20)
        _get(self, key)


# Optional: change the number of users over time. Only defined when SHAPE is set,
# because a shape class takes over from -u / -r / -t.
SHAPE = os.getenv("SHAPE", "").lower()
if SHAPE:

    class DemoShape(LoadTestShape):
        # spike: calm, sudden surge, calm.  ramp: climbs steadily.  wave: rises and falls.
        STAGES = {
            "spike": [(20, 5, 5), (35, 60, 60), (60, 5, 60)],
            "ramp": [(15, 5, 5), (30, 20, 5), (45, 40, 5), (60, 80, 10)],
        }

        def tick(self):
            t = self.get_run_time()
            if SHAPE == "wave":
                if t > 90:
                    return None
                users = 5 + 35 * (1 + math.sin(t / 90 * 2 * math.pi - math.pi / 2)) / 2
                return int(users), 10
            for end, users, rate in self.STAGES.get(SHAPE, []):
                if t < end:
                    return users, rate
            return None