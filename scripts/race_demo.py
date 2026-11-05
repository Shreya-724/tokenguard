"""Show the check-then-act race, and that the Lua scripts do not have it.

Several processes spend from ONE bucket at the same moment. The bucket holds
`--limit` tokens and refills far too slowly to matter, so a correct limiter
allows exactly `--limit` requests in total. Anything above that is a request that
should have been refused.

    python scripts/race_demo.py                       # defaults: 8 processes
    python scripts/race_demo.py --processes 16 --rounds 10
    python scripts/race_demo.py --redis redis://127.0.0.1:6379/5

The "naive" row reads the bucket, computes in Python, then writes it back (three
round trips). The other rows each do the same thing inside one Lua script.
Refuses database 0 and deletes only the keys it made.
"""

import argparse
import multiprocessing
import statistics
import sys
import uuid

import redis

from tokenguard import Limit, NaiveRedisTokenBucket, algorithm_names, get_algorithm

SLOW_REFILL = 0.001  # tokens per second: nothing refills during a round


def spend(job):
    """Runs in its own process, with its own connection."""
    kind, url, prefix, limit, attempts, barrier = job
    client = redis.Redis.from_url(url, decode_responses=True)
    if kind == "naive":
        bucket = NaiveRedisTokenBucket(
            client, "shared", limit, SLOW_REFILL, key_prefix=prefix
        )
        action = lambda: bucket.allow(1).allowed  # noqa: E731
    else:
        algorithm = get_algorithm(kind, client, key_prefix=prefix)
        rule = Limit(capacity=limit, refill_rate=SLOW_REFILL)
        action = lambda: algorithm.check("shared", 1, rule).allowed  # noqa: E731
    client.ping()  # connect before the starting gun
    barrier.wait()
    return sum(1 for _ in range(attempts) if action())


def one_round(kind, url, processes, limit, attempts):
    prefix = f"racedemo:{uuid.uuid4().hex[:8]}:"
    context = multiprocessing.get_context("spawn")
    manager = context.Manager()
    barrier = manager.Barrier(processes)
    try:
        with context.Pool(processes) as pool:
            jobs = [(kind, url, prefix, limit, attempts, barrier)] * processes
            return sum(pool.map(spend, jobs))
    finally:
        client = redis.Redis.from_url(url)
        for key in client.scan_iter(f"{prefix}*"):
            client.delete(key)
        manager.shutdown()


def summarize(counts, limit):
    over = [c - limit for c in counts]
    return {
        "min": min(counts),
        "max": max(counts),
        "mean": statistics.mean(counts),
        "rounds_over": sum(1 for o in over if o > 0),
        "worst_over": max(over),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--redis", default="redis://127.0.0.1:6379/5")
    parser.add_argument("--processes", type=int, default=8)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--attempts", type=int, default=50, help="per process")
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args(argv)

    if args.redis.rstrip("/").endswith("/0"):
        sys.exit("Refusing to use database 0. Pass --redis redis://host:port/5")
    if args.processes * args.attempts <= args.limit:
        sys.exit("processes x attempts must exceed the limit, or nothing is refused")
    redis.Redis.from_url(args.redis).ping()

    print(
        f"{args.processes} processes x {args.attempts} attempts = "
        f"{args.processes * args.attempts} requests against a limit of {args.limit}, "
        f"{args.rounds} rounds\n"
    )
    header = (
        f"{'implementation':<16}{'allowed (min..max)':<22}{'mean':>8}"
        f"{'rounds over':>14}{'worst over':>12}"
    )
    print(header)
    print("-" * len(header))
    wrong = False
    for kind in ["naive", *algorithm_names()]:
        counts = [
            one_round(kind, args.redis, args.processes, args.limit, args.attempts)
            for _ in range(args.rounds)
        ]
        s = summarize(counts, args.limit)
        spread = f"{s['min']}..{s['max']}"
        print(
            f"{kind:<16}{spread:<22}{s['mean']:>8.1f}"
            f"{str(s['rounds_over']) + '/' + str(args.rounds):>14}{s['worst_over']:>12}"
        )
        if kind != "naive" and s["rounds_over"]:
            wrong = True
    print(f"\ncorrect answer every round: exactly {args.limit} allowed.")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
