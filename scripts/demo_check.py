"""Is everything up for the demo? Run this before you start recording.

    python scripts/demo_check.py
    python scripts/demo_check.py --base http://localhost:8000 --prefix tg

Checks Redis, the Django server, the sign-in endpoint (and its CSRF cookie),
and whether any traffic has been recorded lately. It cannot see the feed
process: after it passes, open the dashboard and look for CONNECTED in the top
bar with "frame just now". Exit code 1 if something it needs is missing.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

import redis

from tokenguard.metrics import MetricsReader

failed = False


def report(status: str, message: str) -> None:
    global failed
    if status == "FAIL":
        failed = True
    print(f"{status:<5} {message}")


def get(url: str):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, response.headers, response.read()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument(
        "--redis-url", default=os.getenv("REDIS_URL", "redis://localhost:6379/0")
    )
    parser.add_argument("--prefix", default="tg", help="the KEY_PREFIX setting")
    args = parser.parse_args()

    client = redis.Redis.from_url(args.redis_url, decode_responses=True)
    try:
        client.ping()
        report("ok", f"Redis answers at {args.redis_url}")
    except redis.RedisError as exc:
        report("FAIL", f"Redis is not reachable ({exc}): docker compose up -d")
        client = None

    try:
        status, _, _ = get(f"{args.base}/health/")
        report("ok", f"server answers at {args.base} (/health/ -> {status})")
    except (urllib.error.URLError, OSError) as exc:
        report("FAIL", f"server not reachable at {args.base} ({exc}): runserver?")
        return 1

    try:
        status, headers, body = get(f"{args.base}/tokenguard/session/")
        who = json.loads(body)
        cookies = " ".join(headers.get_all("Set-Cookie") or [])
        report("ok", f"sign-in endpoint answers (signed in: {who['authenticated']})")
        if "csrftoken" in cookies:
            report("ok", "it hands out the CSRF cookie the dashboard needs")
        else:
            report("FAIL", "no csrftoken cookie from /tokenguard/session/")
    except urllib.error.HTTPError as exc:
        report(
            "FAIL",
            f"/tokenguard/session/ gave HTTP {exc.code}: is api_urls included?",
        )
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        report("FAIL", f"/tokenguard/session/ is not usable ({exc})")

    if client is not None:
        try:
            reader = MetricsReader(client, key_prefix=f"{args.prefix}:")
            recent = reader.summary(15)
            if recent.requests:
                report(
                    "ok",
                    f"metrics are recording: {recent.requests} requests in 15 s "
                    f"({recent.blocked} blocked)",
                )
            else:
                report(
                    "warn",
                    "no traffic in the last 15 s: start scripts/load_demo.py, and "
                    'check "METRICS": True in settings',
                )
            rules = client.hgetall(f"{args.prefix}:{{rules}}")
            overrides = [k for k in rules if k != "__version__"]
            if overrides:
                report(
                    "warn",
                    f"live overrides exist for {overrides}: reset them in the rule "
                    "editor (or tokenguard_rules.py delete) for a clean demo",
                )
            else:
                report("ok", "no leftover live rule overrides")
        except redis.RedisError as exc:
            report("FAIL", f"could not read metrics ({exc})")

    print("\nNow open the dashboard: the top bar should say CONNECTED, frame just now.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
