"""Ask tokenguard what is happening, from the command line.

    python scripts/tokenguard_stats.py stats                 # last 60 seconds
    python scripts/tokenguard_stats.py top                   # who uses the most
    python scripts/tokenguard_stats.py top --by blocked      # who is turned away
    python scripts/tokenguard_stats.py routes                # per rule
    python scripts/tokenguard_stats.py series --seconds 30   # per second
    python scripts/tokenguard_stats.py bucket api ip:1.2.3.4 --capacity 60 \\
        --refill-rate 1                                      # one key's level
    python scripts/tokenguard_stats.py watch                 # live, every second

The servers need "METRICS": True. Options, given before the command:
--redis-url (default $REDIS_URL) and --prefix (default "tg", the KEY_PREFIX
setting).
"""

import argparse
import os
import sys
import time

import redis

from tokenguard.algorithms import Limit
from tokenguard.metrics import MetricsReader


def show_stats(reader, seconds):
    s = reader.summary(seconds)
    print(
        f"last {s.seconds}s: {s.requests} requests, {s.allowed} allowed, "
        f"{s.blocked} blocked ({s.blocked_ratio:.1%}), "
        f"{s.requests_per_second:.2f} req/s, {s.tokens:g} tokens"
    )


def show_top(reader, n, minutes, by):
    rows = reader.top_consumers(n=n, minutes=minutes, by=by)
    if not rows:
        print("  (nobody yet)")
    for i, c in enumerate(rows, 1):
        print(f"  {i:>2}. {c.key:<40} {c.tokens:>12g} tokens {c.blocked:>6} blocked")


def show_routes(reader, minutes):
    rows = reader.routes(minutes)
    if not rows:
        print("  (no traffic yet)")
    for r in rows:
        print(
            f"  {r.scope:<40} {r.requests:>7} requests {r.blocked_ratio:>7.1%} "
            f"blocked {r.tokens:>10g} tokens"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--redis-url", default=os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    parser.add_argument("--prefix", default="tg", help="the KEY_PREFIX setting")
    cmds = parser.add_subparsers(dest="command", required=True)
    p = cmds.add_parser("stats", help="totals and blocked ratio")
    p.add_argument("--seconds", type=int, default=60)
    p = cmds.add_parser("top", help="the heaviest consumers")
    p.add_argument("-n", type=int, default=10)
    p.add_argument("--minutes", type=int, default=5)
    p.add_argument("--by", choices=["tokens", "blocked"], default="tokens")
    p = cmds.add_parser("routes", help="per-rule totals")
    p.add_argument("--minutes", type=int, default=5)
    p = cmds.add_parser("series", help="requests per second (or per --step)")
    p.add_argument("--seconds", type=int, default=30)
    p.add_argument("--step", type=int, default=1)
    p = cmds.add_parser("bucket", help="how much of a limit one key has left")
    p.add_argument("scope")
    p.add_argument("identity")
    p.add_argument("--capacity", type=float, required=True)
    p.add_argument("--refill-rate", type=float, required=True)
    p.add_argument("--algorithm", default="token_bucket")
    p = cmds.add_parser("watch", help="refresh every second (Ctrl+C to stop)")
    p.add_argument("--seconds", type=int, default=10)
    args = parser.parse_args(argv)

    client = redis.Redis.from_url(args.redis_url, decode_responses=True)
    reader = MetricsReader(client, key_prefix=f"{args.prefix}:")
    try:
        if args.command == "stats":
            show_stats(reader, args.seconds)
        elif args.command == "top":
            show_top(reader, args.n, args.minutes, args.by)
        elif args.command == "routes":
            show_routes(reader, args.minutes)
        elif args.command == "series":
            for pt in reader.timeseries(args.seconds, args.step):
                when = time.strftime("%H:%M:%S", time.localtime(pt.ts))
                bar = "#" * min(60, pt.allowed) + "x" * min(60, pt.blocked)
                print(f"{when}  {pt.allowed:>5} ok {pt.blocked:>5} blocked  {bar}")
        elif args.command == "bucket":
            level = reader.bucket_level(
                args.scope,
                args.identity,
                Limit(args.capacity, args.refill_rate),
                algorithm=args.algorithm,
            )
            reset = level.reset_after
            full_in = "n/a" if reset is None else f"{reset:.1f}s"
            print(
                f"{level.key}: {level.remaining:g} of {level.capacity:g} left "
                f"({level.algorithm}), full again in {full_in}"
            )
        else:
            while True:
                print("\033[2J\033[H", end="")  # clear the screen
                show_stats(reader, args.seconds)
                print("top consumers:")
                show_top(reader, 5, 1, "tokens")
                print("most blocked:")
                show_top(reader, 5, 1, "blocked")
                time.sleep(1)
    except redis.RedisError as exc:
        print(f"could not reach Redis: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
