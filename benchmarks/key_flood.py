"""What a flood of one-off callers does to Redis, and what limits it (Week 7, Day 7).

    python benchmarks/key_flood.py --yes                     # the defaults
    python benchmarks/key_flood.py --yes --keys 100000 --headroom-mb 4

An attacker who can make every request look like a new caller (a fresh API key,
a fresh X-Forwarded-For) gets a new Redis key each time. This sends --keys such
callers at the limiter, with Redis allowed only --headroom-mb of memory above
what it uses now, once for each --policies value, and reports what happened:

    noeviction    Redis refuses new writes when full. tokenguard turns that into
                  "Redis unavailable", so FAIL_MODE decides each request's fate.
    volatile-lru  Redis evicts keys that have a TTL, least recently used first.
                  Memory stays bounded and requests keep working, but an evicted
                  caller's bucket starts full again.

WARNING: maxmemory is a setting of the whole Redis server, not of one database.
This changes it while the test runs and puts it back afterwards, and it empties
the database in the URL (use a throwaway one, not 0). It refuses to run without
--yes. Do not point it at a Redis that real traffic is using.
"""

import argparse
import sys
import uuid
from urllib.parse import urlparse

import redis

from tokenguard import Limit, get_algorithm
from tokenguard.errors import RedisUnavailableError

LIMIT = Limit(capacity=5, refill_rate=1)  # every key expires 10 seconds after use


def info(client, section):
    reply = client.execute_command("INFO", section)
    if isinstance(reply, dict):
        return reply
    out = {}
    for line in str(reply).splitlines():
        if ":" in line and not line.startswith("#"):
            name, _, value = line.partition(":")
            out[name] = value.strip()
    return out


def config_get(client, name):
    reply = client.execute_command("CONFIG", "GET", name)
    if isinstance(reply, dict):
        return reply[name]
    return reply[reply.index(name) + 1]


def config_set(client, name, value):
    client.execute_command("CONFIG", "SET", name, str(value))


def flood(client, keys):
    """Send `keys` one-off callers. Returns (allowed, errors)."""
    algo = get_algorithm("token_bucket", client, key_prefix="flood:")
    allowed = errors = 0
    for _ in range(keys):
        try:
            if algo.check(f"caller-{uuid.uuid4().hex}", 1, LIMIT).allowed:
                allowed += 1
        except RedisUnavailableError:
            errors += 1
    return allowed, errors


def run_policy(client, policy, keys, headroom):
    client.flushdb()
    config_set(client, "maxmemory", 0)
    config_set(client, "maxmemory-policy", policy)
    base = int(info(client, "memory")["used_memory"])
    config_set(client, "maxmemory", base + headroom)
    evicted_before = int(info(client, "stats")["evicted_keys"])
    allowed, errors = flood(client, keys)
    used = int(info(client, "memory")["used_memory"])
    return {
        "policy": policy,
        "requests": keys,
        "allowed": allowed,
        "errors": errors,
        "evicted": int(info(client, "stats")["evicted_keys"]) - evicted_before,
        "keys_left": client.execute_command("DBSIZE"),
        "limit_mb": headroom / 1e6,
        "growth_mb": (used - base) / 1e6,
    }


def unlimited_cost(client, keys):
    """Bytes per one-off caller with no memory limit: the size of the problem."""
    client.flushdb()
    config_set(client, "maxmemory", 0)
    base = int(info(client, "memory")["used_memory"])
    flood(client, keys)
    grown = int(info(client, "memory")["used_memory"]) - base
    return grown / keys, client.execute_command("DBSIZE")


def render(per_key, unlimited_keys, rows):
    lines = [
        f"With no memory limit each one-off caller costs about {per_key:,.0f} bytes "
        f"({unlimited_keys:,} keys alive at the end).",
        "",
        "| policy | requests | allowed | refused (Redis full) | evicted | keys left "
        "| allowed growth MB | actual growth MB |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['policy']} | {r['requests']:,} | {r['allowed']:,} | {r['errors']:,} "
            f"| {r['evicted']:,} | {r['keys_left']:,} | {r['limit_mb']:.1f} "
            f"| {r['growth_mb']:.1f} |"
        )
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("url", nargs="?", default="redis://127.0.0.1:6379/5")
    parser.add_argument("--keys", type=int, default=30_000)
    parser.add_argument("--headroom-mb", type=float, default=2.0)
    parser.add_argument("--policies", default="noeviction,volatile-lru")
    parser.add_argument("--yes", action="store_true", help="I read the WARNING")
    args = parser.parse_args(argv)
    if not args.yes:
        sys.exit(__doc__ + "\nRe-run with --yes to go ahead.")
    if (urlparse(args.url).path.strip("/") or "0") == "0":
        sys.exit("use a throwaway database, e.g. redis://127.0.0.1:6379/5 (not 0)")

    client = redis.Redis.from_url(args.url, decode_responses=True)
    client.ping()
    old = {n: config_get(client, n) for n in ("maxmemory", "maxmemory-policy")}
    headroom = int(args.headroom_mb * 1_000_000)
    try:
        per_key, alive = unlimited_cost(client, args.keys)
        rows = [
            run_policy(client, policy, args.keys, headroom)
            for policy in args.policies.split(",")
        ]
    finally:
        client.flushdb()
        config_set(client, "maxmemory", old["maxmemory"])
        config_set(client, "maxmemory-policy", old["maxmemory-policy"])
    print(render(per_key, alive, rows))


if __name__ == "__main__":
    main()
