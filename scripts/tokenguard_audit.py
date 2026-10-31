"""Audit the keys tokenguard keeps in Redis: how many, how big, and do they expire?

    python scripts/tokenguard_audit.py                      # report only
    python scripts/tokenguard_audit.py --fix                # give immortal keys a TTL
    python scripts/tokenguard_audit.py redis://127.0.0.1:6379/0 --prefix tg

Every key tokenguard writes should expire, except the live-rules hash (rules stay
until you change them). A key without an expiry never goes away, and a client
that can create keys can then fill Redis. Earlier versions had one such leak
(sliding window, after a refund); --fix gives those keys a TTL (default 1 day).

Read-only unless --fix is given. It scans with SCAN, so it does not block Redis.
"""

import argparse
import os
import sys
from collections import defaultdict

import redis

SAMPLE = 200  # keys per kind whose size is measured


def kind_of(key, prefix):
    rest = key[len(prefix) + 1 :] if key.startswith(f"{prefix}:") else key
    if rest.startswith("{rules}"):
        return "live rules"
    if rest.startswith("metrics:"):
        return "metrics"
    if rest.startswith("sw:"):
        return "sliding window"
    if rest.startswith("fw:"):
        return "fixed window"
    if ":bucket:" in rest or ":day:" in rest or ":month:" in rest:
        return "budget"
    return "token bucket"


def audit(client, prefix, fix=False, ttl=86_400):
    found = defaultdict(lambda: {"keys": 0, "no_ttl": 0, "bytes": 0, "sampled": 0})
    for key in client.scan_iter(f"{prefix}:*", count=1000):
        kind = kind_of(key, prefix)
        row = found[kind]
        row["keys"] += 1
        if client.ttl(key) == -1 and kind != "live rules":
            row["no_ttl"] += 1
            if fix:
                client.expire(key, ttl)
        if row["sampled"] < SAMPLE:
            row["bytes"] += client.execute_command("MEMORY", "USAGE", key) or 0
            row["sampled"] += 1
    return dict(found)


def render(found, fixed):
    lines = [
        f"{'kind':<16}{'keys':>10}{'no TTL':>10}{'avg bytes':>12}{'est. total':>14}",
    ]
    for kind, row in sorted(found.items()):
        avg = row["bytes"] / row["sampled"] if row["sampled"] else 0
        lines.append(
            f"{kind:<16}{row['keys']:>10,}{row['no_ttl']:>10,}"
            f"{avg:>12,.0f}{avg * row['keys'] / 1e6:>12.2f} MB"
        )
    leaks = sum(r["no_ttl"] for r in found.values())
    if leaks and fixed:
        lines.append(f"\nGave {leaks:,} keys without an expiry a TTL.")
    elif leaks:
        lines.append(f"\n{leaks:,} keys never expire. Run again with --fix.")
    else:
        lines.append("\nEvery key expires (the live-rules hash is exempt).")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "url", nargs="?", default=os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    parser.add_argument("--prefix", default="tg", help="the KEY_PREFIX setting")
    parser.add_argument(
        "--fix", action="store_true", help="set a TTL on keys without one"
    )
    parser.add_argument("--ttl", type=int, default=86_400, help="seconds, for --fix")
    args = parser.parse_args(argv)
    client = redis.Redis.from_url(args.url, decode_responses=True)
    try:
        client.ping()
    except redis.RedisError as exc:
        sys.exit(f"cannot reach Redis at {args.url}: {exc}")
    found = audit(client, args.prefix, args.fix, args.ttl)
    print(render(found, args.fix) if found else f"no keys under {args.prefix}:*")


if __name__ == "__main__":
    main()
