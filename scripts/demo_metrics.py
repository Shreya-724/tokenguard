"""See the metrics answer "who is using the most right now?" (no server needed).

    python scripts/demo_metrics.py

Sends simulated traffic through a real limiter and the metrics recorder in
your local Redis, then asks the reader the questions the dashboard will ask.
Uses its own key prefix and cleans up after itself.
"""

import os
import random
import uuid

import redis

from tokenguard.algorithms import Limit, get_algorithm
from tokenguard.metrics import MetricsReader, MetricsRecorder

URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
PREFIX = f"demo-metrics-{uuid.uuid4().hex[:6]}:"

client = redis.Redis.from_url(URL, decode_responses=True)
limiter = get_algorithm("token_bucket", client, key_prefix=PREFIX)
recorder = MetricsRecorder(client, PREFIX)
reader = MetricsReader(client, PREFIX)
LIMIT = Limit(capacity=100, refill_rate=1)

# alice is a heavy user, bob a normal one, mallory hammers the API
traffic = {"alice": 60, "bob": 15, "mallory": 400, "carol": 5}
random.seed(1)
calls = [name for name, n in traffic.items() for _ in range(n)]
random.shuffle(calls)
try:
    for name in calls:
        decision = limiter.check(f"api:user:{name}", 1, LIMIT)
        recorder.record("api", f"user:{name}", allowed=decision.allowed, tokens=1)

    print("Last 60 seconds")
    print(" ", reader.summary(60).as_dict())
    print("\nWho is using the most?")
    for c in reader.top_consumers(n=3):
        print(f"  {c.identity:<14} {c.tokens:>5g} tokens spent, {c.blocked} blocked")
    print("\nWho is being turned away the most?")
    for c in reader.top_consumers(n=3, by="blocked"):
        print(f"  {c.identity:<14} {c.blocked:>5} blocked")
    print("\nHow much has mallory got left right now?")
    level = reader.bucket_level("api", "user:mallory", LIMIT, key_prefix=PREFIX)
    print(f"  {level.remaining:.1f} of {level.capacity:g} tokens")
finally:
    for key in client.scan_iter(f"{PREFIX}*"):
        client.delete(key)
