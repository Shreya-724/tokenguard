"""Measure the limiter itself, with no web server or Django in the way.

    python benchmarks/limiter_bench.py [redis://127.0.0.1:6379/5] [--calls 5000]

Times one call at a time (microseconds, network round trip included) for:

    redis PING            the floor: one round trip and nothing else
    token_bucket          check() on a key that is always allowed
    token_bucket+metrics  the same, then the dashboard metrics write
    token_bucket/new key  check() on a key that does not exist yet
    fixed_window          check() on a key that is always allowed
    sliding_window        check() on a key that is always allowed

The difference from PING is the cost of the limiter's own work. The raw
timings go to benchmarks/results/limiter-<time>/ as CSV, with a summary.md.
Run it on the same machine as the load test, so the two can be compared.
"""

import argparse
import csv
import math
import platform
import statistics
import time
import uuid
from datetime import datetime
from pathlib import Path

import redis

from tokenguard import Limit, MetricsRecorder, get_algorithm

HERE = Path(__file__).resolve().parent
ALWAYS = Limit(capacity=1e9, refill_rate=1e9)


def percentile(sorted_values, q):
    """Nearest-rank percentile of an already sorted list."""
    index = max(
        0, min(len(sorted_values) - 1, math.ceil(q / 100 * len(sorted_values)) - 1)
    )
    return sorted_values[index]


def summarise(samples):
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "mean": statistics.fmean(ordered),
        "p50": percentile(ordered, 50),
        "p95": percentile(ordered, 95),
        "p99": percentile(ordered, 99),
        "max": ordered[-1],
    }


def timed(fn, calls, warmup=200):
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(calls):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1e6)
    return samples


def build_cases(client, prefix):
    def algo(name):
        return get_algorithm(name, client, key_prefix=f"{prefix}{name}:")

    bucket, fixed, sliding = (
        algo("token_bucket"),
        algo("fixed_window"),
        algo("sliding_window"),
    )
    recorder = MetricsRecorder(client, key_prefix=f"{prefix}m:")

    def bucket_and_metrics():
        bucket.check("k", 1, ALWAYS)
        recorder.record("bench", "k", allowed=True, tokens=1)

    return {
        "redis PING": client.ping,
        "token_bucket": lambda: bucket.check("k", 1, ALWAYS),
        "token_bucket+metrics": bucket_and_metrics,
        "token_bucket/new key": lambda: bucket.check(uuid.uuid4().hex, 1, ALWAYS),
        "fixed_window": lambda: fixed.check("k", 1, ALWAYS),
        "sliding_window": lambda: sliding.check("k", 1, ALWAYS),
    }


def redis_version(client):
    try:
        return client.info("server")["redis_version"]
    except Exception:
        return "unknown"


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="redis://127.0.0.1:6379/5")
    parser.add_argument("--calls", type=int, default=5000)
    args = parser.parse_args(argv)
    client = redis.Redis.from_url(args.url)
    client.ping()
    prefix = f"lb:{uuid.uuid4().hex[:8]}:"  # throwaway keys, deleted at the end
    out = HERE / "results" / f"limiter-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True)
    rows, raw = [], {}
    try:
        for name, fn in build_cases(client, prefix).items():
            raw[name] = timed(fn, args.calls)
            rows.append((name, summarise(raw[name])))
    finally:
        for key in client.scan_iter(f"{prefix}*"):
            client.delete(key)
    with open(out / "raw_us.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case", "microseconds"])
        for name, samples in raw.items():
            writer.writerows((name, f"{value:.1f}") for value in samples)
    floor = rows[0][1]["p50"]
    lines = [
        "# Limiter latency (no web server)",
        "",
        f"- started: {datetime.now():%Y-%m-%d %H:%M:%S}",
        f"- platform: {platform.platform()}, Python {platform.python_version()}",
        f"- redis: {redis_version(client)}, {args.calls} calls per case",
        "",
        "Microseconds per call. `p50 over PING` is the median minus the median of a "
        "bare PING: the limiter's own cost.",
        "",
        "| case | mean | p50 | p95 | p99 | max | p50 over PING |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, s in rows:
        lines.append(
            f"| {name} | {s['mean']:.0f} | {s['p50']:.0f} | {s['p95']:.0f} "
            f"| {s['p99']:.0f} | {s['max']:.0f} | {s['p50'] - floor:+.0f} |"
        )
    (out / "summary.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
