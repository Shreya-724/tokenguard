"""Helpers shared by concurrency tests and scripts (must be importable by workers)."""

from tokenguard import NaiveRedisTokenBucket, RedisTokenBucket
from tokenguard.redis_client import create_client


def build(impl, url, key, capacity, rate):
    # Generous timeouts: 50 threads opening connections at once can be slow
    # on Docker Desktop (Windows/Mac). Production default stays at 0.5s.
    client = create_client(url, socket_timeout=5.0, socket_connect_timeout=5.0)
    cls = NaiveRedisTokenBucket if impl == "naive" else RedisTokenBucket
    # real clock (WallClock / Redis TIME); key_prefix='' so tests can clean up `key`
    return cls(client, key, capacity, rate, key_prefix="")


def run_batch(args):
    """Run in a separate process: make n requests, return how many were allowed."""
    impl, url, key, capacity, rate, n = args
    bucket = build(impl, url, key, capacity, rate)
    return sum(bucket.allow().allowed for _ in range(n))
