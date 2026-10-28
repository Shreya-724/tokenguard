"""Where does one limited request spend its time? (Week 7, Day 3)

    python benchmarks/profile_limiter.py [redis://127.0.0.1:6379/5] [--calls 3000]

Runs the same decision three ways, with no web server in the way:

    check only             one token-bucket check (the unavoidable round trip)
    check + metrics        the check, then the dashboard metrics write
    check + buffered       the check, and metrics queued for a background flush

For each it counts Redis round trips per call and splits the time per call into
"in Redis" (waiting for the network and the server) and "in Python" (everything
else). It also writes a cProfile of the second case to profile.txt, so you can
see which functions cost the most.

Round trips are counted at redis-py's execute_command and Pipeline.execute.
redis-py also sends a SCRIPT EXISTS before a pipeline that uses scripts; that
is not counted, and it happens once per flush, not once per call.
"""

import argparse
import cProfile
import io
import pstats
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import redis

from tokenguard import Limit, MetricsRecorder, get_algorithm

HERE = Path(__file__).resolve().parent
ALWAYS = Limit(capacity=1e9, refill_rate=1e9)


class Counter:
    """Counts round trips (all threads) and Redis time (the calling thread)."""

    def __init__(self):
        self.trips = 0
        self.redis_seconds = 0.0
        self._owner = threading.get_ident()
        self._lock = threading.Lock()

    def reset(self):
        self.trips = 0
        self.redis_seconds = 0.0

    def hit(self, seconds):
        with self._lock:
            self.trips += 1
            if threading.get_ident() == self._owner:
                self.redis_seconds += seconds


def install(counter):
    """Wrap redis-py so every round trip is counted. Returns an undo function."""
    original_execute = redis.Redis.execute_command
    original_pipeline = redis.Redis.pipeline

    def execute_command(self, *args, **kwargs):
        start = time.perf_counter()
        try:
            return original_execute(self, *args, **kwargs)
        finally:
            counter.hit(time.perf_counter() - start)

    def pipeline(self, *args, **kwargs):
        pipe = original_pipeline(self, *args, **kwargs)
        real_execute = pipe.execute

        def execute(*a, **k):
            start = time.perf_counter()
            try:
                return real_execute(*a, **k)
            finally:
                counter.hit(time.perf_counter() - start)

        pipe.execute = execute
        return pipe

    redis.Redis.execute_command = execute_command
    redis.Redis.pipeline = pipeline

    def undo():
        redis.Redis.execute_command = original_execute
        redis.Redis.pipeline = original_pipeline

    return undo


def measure(name, step, calls, counter, after=None):
    for i in range(300):  # warm up: connections, script loading, caches
        step(i)
    if after:
        after()
    counter.reset()
    total = 0.0
    for i in range(calls):
        start = time.perf_counter()
        step(i)
        total += time.perf_counter() - start
    if after:
        after()  # send what is still queued, so its round trips are counted
    per_call = total / calls * 1e6
    in_redis = counter.redis_seconds / calls * 1e6
    return {
        "name": name,
        "trips": counter.trips / calls,
        "total_us": per_call,
        "redis_us": in_redis,
        "python_us": per_call - in_redis,
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="redis://127.0.0.1:6379/5")
    parser.add_argument("--calls", type=int, default=3000)
    parser.add_argument("--flush", type=float, default=0.2, help="buffered interval")
    args = parser.parse_args(argv)

    client = redis.Redis.from_url(args.url, decode_responses=True)
    client.ping()
    prefix = f"pl:{uuid.uuid4().hex[:8]}:"
    algo = get_algorithm("token_bucket", client, key_prefix=f"{prefix}tb:")
    sync = MetricsRecorder(client, key_prefix=f"{prefix}m1:")
    buffered = MetricsRecorder(
        client, key_prefix=f"{prefix}m2:", flush_interval=args.flush
    )
    counter = Counter()
    undo = install(counter)

    def check(i):
        algo.check(f"caller-{i % 20}", 1, ALWAYS)

    def check_and_metrics(i):
        decision = algo.check(f"caller-{i % 20}", 1, ALWAYS)
        sync.record("bench", f"caller-{i % 20}", allowed=decision.allowed, tokens=1)

    def check_and_buffered(i):
        decision = algo.check(f"caller-{i % 20}", 1, ALWAYS)
        who = f"caller-{i % 20}"
        buffered.record("bench", who, allowed=decision.allowed, tokens=1)

    out = HERE / "results" / f"profile-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True)
    try:
        rows = [
            measure("check only", check, args.calls, counter),
            measure("check + metrics", check_and_metrics, args.calls, counter),
            measure(
                f"check + buffered ({args.flush:g}s)",
                check_and_buffered,
                args.calls,
                counter,
                after=buffered.flush,
            ),
        ]
        profiler = cProfile.Profile()
        profiler.enable()
        for i in range(args.calls):
            check_and_metrics(i)
        profiler.disable()
    finally:
        undo()
        buffered.close()
        for key in client.scan_iter(f"{prefix}*"):
            client.delete(key)

    buf = io.StringIO()
    stats = pstats.Stats(profiler, stream=buf).sort_stats("tottime")
    buf.write("== by time inside each function (tottime) ==\n")
    stats.print_stats(15)
    buf.write("\n== by time including callees (cumulative) ==\n")
    stats.sort_stats("cumulative").print_stats(15)
    (out / "profile.txt").write_text(buf.getvalue())

    base = rows[0]
    lines = [
        "# Where one decision spends its time (no web server)",
        "",
        f"- started: {datetime.now():%Y-%m-%d %H:%M:%S}, {args.calls} calls per case",
        f"- redis: {args.url}",
        "",
        "Microseconds per call. `in Redis` is time waiting on Redis round trips "
        "(network included); `in Python` is the rest.",
        "",
        "| case | round trips/call | total | in Redis | in Python | vs check only |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['name']} | {r['trips']:.2f} | {r['total_us']:.0f} "
            f"| {r['redis_us']:.0f} | {r['python_us']:.0f} "
            f"| {r['total_us'] - base['total_us']:+.0f} |"
        )
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nSaved {out}  (profile.txt has the function-level view)")


if __name__ == "__main__":
    main()
