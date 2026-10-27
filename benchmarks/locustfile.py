"""Load scenarios for tokenguard. Run through benchmarks/run_bench.py, or by hand:

    locust -f benchmarks/locustfile.py --headless -u 50 -r 50 -t 30s \
        --host http://127.0.0.1:8000 AllowedUser

Three scenarios, one user class each (pass the class name to pick one):

    AllowedUser    traffic that is (almost) never limited: 20 callers, huge limits
    BlockedUser    traffic that is (almost) always limited: 5 callers, 1 token each
    DistinctUser   a brand new caller on every request: the worst case for keys

A 429 is the limiter doing its job, so it counts as a success here. Real
failures (5xx, timeouts, connection errors) count as failures. The 200/429
split is written to the file named by BENCH_STATUS_FILE when the run ends.
"""

import json
import os
import random
import uuid
from collections import Counter

from locust import FastHttpUser, constant, events, task

STATUS = Counter()


def _get(user, path, api_key):
    with user.client.get(
        path, headers={"X-API-Key": api_key}, catch_response=True
    ) as response:
        STATUS[response.status_code] += 1
        if response.status_code in (200, 429):
            response.success()
        else:
            response.failure(f"HTTP {response.status_code}")


class AllowedUser(FastHttpUser):
    wait_time = constant(0)  # closed loop: as fast as the server answers

    def on_start(self):
        self.caller = f"caller-{random.randrange(20)}"  # 20 callers share the load

    @task
    def hit(self):
        _get(self, "/bench/allowed/", self.caller)


class BlockedUser(FastHttpUser):
    wait_time = constant(0)

    def on_start(self):
        self.caller = f"caller-{random.randrange(5)}"

    @task
    def hit(self):
        _get(self, "/bench/blocked/", self.caller)


class DistinctUser(FastHttpUser):
    wait_time = constant(0)

    @task
    def hit(self):
        _get(self, "/bench/distinct/", uuid.uuid4().hex)


@events.quitting.add_listener
def _write_status(environment, **_):
    path = os.getenv("BENCH_STATUS_FILE")
    if path:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({str(code): n for code, n in sorted(STATUS.items())}, handle)
