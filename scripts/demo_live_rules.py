"""Demo: change a limit while the server runs, and watch behavior change.

Usage:  python scripts/demo_live_rules.py [http://localhost:8000]

Needs Redis and the demo server running with "LIVE_RULES": True in the demo
settings (see docs/live-rules.md). Uses the /login/ rule: 5 requests, then 429.
It sets a new limit through Redis, and measures how long the server takes to
notice (at most LIVE_RULES_TTL seconds), then puts everything back.
"""

import os
import sys
import time
import urllib.error
import urllib.request

import redis

from tokenguard.rulestore import RuleStore

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"
URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
store = RuleStore(redis.Redis.from_url(URL, decode_responses=True), "tg:", ttl=0)


def hit(path="/login/"):
    try:
        with urllib.request.urlopen(BASE + path) as response:
            return response.status, response.headers
    except urllib.error.HTTPError as error:
        return error.code, error.headers


def show(label, status, headers):
    print(
        f"  {label:<26} {status}  limit {headers.get('X-RateLimit-Limit')}"
        f"  rules v{headers.get('X-TokenGuard-Rules-Version')}"
    )


store.delete_rule("login")  # start from the settings
time.sleep(0.1)
print("1. The configured rule: 5 requests, then blocked")
status = 200
for i in range(7):
    status, headers = hit()
    show(f"request {i + 1}", status, headers)
if headers.get("X-TokenGuard-Rules-Version") is None:
    sys.exit("The server is not running with LIVE_RULES enabled.")

print("\n2. Raise the limit live: capacity 20, refilling 2/second")
started = time.monotonic()
version = store.set_rule("login", capacity=20, refill_rate=2)
print(f"  rules version is now {version}; waiting for the server to notice...")
while True:
    status, headers = hit()
    if headers.get("X-RateLimit-Limit") == "20":
        break
    time.sleep(0.25)
    if time.monotonic() - started > 60:
        sys.exit("The server never picked up the change.")
print(f"  noticed after {time.monotonic() - started:.1f} seconds")
show("first request", status, headers)
if status == 429:
    print("  (blocked: the bigger bucket is still filling at the new rate)")

print("\n3. It really behaves differently now")
time.sleep(3)  # refilling at 2/second
codes = [hit()[0] for _ in range(6)]
print(f"  6 quick requests: {codes}")

print("\n4. Put it back")
store.delete_rule("login")
print("  override removed: the server returns to the configured rule shortly")
