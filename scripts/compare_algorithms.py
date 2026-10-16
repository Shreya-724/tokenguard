"""Compare the rate-limit algorithms on the things that differ.

Usage:  python scripts/compare_algorithms.py [redis://localhost:6379/0]

Prints a Markdown table:
  edge burst     requests let through in 0.1 seconds across a window edge, for
                 a limit of 10 per 10 seconds (a fair limit would allow 10)
  bytes per key  Redis MEMORY USAGE for one key whose limit is fully used,
                 for limits of 10 and 1,000 requests
  median us      time of one check() call against a key whose limit of 100 is
                 full (so a sliding window holds 100 entries), including the
                 network round trip. It depends on your machine: compare the
                 rows, not the absolute numbers

It uses throwaway keys (prefix "cmp:") and deletes them afterwards.
"""

import statistics
import sys
import time
import uuid

import redis

from tokenguard import FakeClock
from tokenguard.algorithms import Limit, algorithm_names, get_algorithm

URL = sys.argv[1] if len(sys.argv) > 1 else "redis://localhost:6379/0"
client = redis.Redis.from_url(URL, decode_responses=True)
prefix = f"cmp:{uuid.uuid4().hex[:8]}:"


def edge_burst(name):
    """Requests allowed in 0.1s around a window edge (limit: 10 per 10s)."""
    clock = FakeClock()
    algo = get_algorithm(name, client, clock, f"{prefix}{name}:edge:")
    rule = Limit(capacity=10, refill_rate=1)
    allowed = 0
    for moment in (9.9, 10.0):
        clock.set(moment)
        allowed += sum(algo.check("k", 1, rule).allowed for _ in range(10))
    return allowed


def bytes_per_key(name, limit):
    """MEMORY USAGE of one key after `limit` requests of cost 1 (a full limit)."""
    clock = FakeClock(1_000.0)
    tag = f"{prefix}{name}:mem{limit}:"
    algo = get_algorithm(name, client, clock, tag)
    rule = Limit(capacity=limit, refill_rate=1)
    for _ in range(limit):
        algo.check("k", 1, rule)
    keys = list(client.scan_iter(f"{tag}*"))
    assert len(keys) == 1, keys
    return client.execute_command("MEMORY", "USAGE", keys[0])


def median_microseconds(name, calls=1_000):
    algo = get_algorithm(name, client, key_prefix=f"{prefix}{name}:lat:")
    rule = Limit(capacity=100, refill_rate=0.01)  # a 10,000 second window
    for _ in range(100):  # fill the limit (this also loads the script)
        algo.check("k", 1, rule)
    times = []
    for _ in range(calls):
        start = time.perf_counter()
        algo.check("k", 1, rule)
        times.append((time.perf_counter() - start) * 1e6)
    return statistics.median(times)


rows = []
try:
    for name in algorithm_names():
        rows.append(
            (
                name,
                edge_burst(name),
                bytes_per_key(name, 10),
                bytes_per_key(name, 1_000),
                median_microseconds(name),
            )
        )
finally:
    for key in client.scan_iter(f"{prefix}*"):
        client.delete(key)

print(
    "| algorithm | edge burst (fair: 10) | bytes/key, limit 10 | "
    "bytes/key, limit 1,000 | median us/check |"
)
print("|---|---|---|---|---|")
for name, burst, small, large, micros in rows:
    print(f"| {name} | {burst} | {small} | {large:,} | {micros:.0f} |")
