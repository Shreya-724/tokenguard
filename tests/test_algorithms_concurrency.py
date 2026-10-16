"""The same concurrency test for every algorithm: exactly the limit, no more.

Many OS processes hammer one key. If an algorithm read, decided and wrote in
separate steps, two processes could both see room for the last unit. Each
algorithm does it in one Lua script, so the count is exact every time.
"""

import multiprocessing
import uuid

import pytest
import redis

from tokenguard.algorithms import Limit, algorithm_names, get_algorithm

PROCESSES = 8
ATTEMPTS = 50  # per process: 400 attempts for a limit of 100
RULE = Limit(capacity=100, refill_rate=0.01)  # a 10,000 second window


def hammer(job):
    """Runs in its own process, with its own Redis connection."""
    name, prefix, url = job
    client = redis.Redis.from_url(url, decode_responses=True)
    algorithm = get_algorithm(name, client, key_prefix=prefix)
    return sum(algorithm.check("k", 1, RULE).allowed for _ in range(ATTEMPTS))


@pytest.mark.parametrize("name", list(algorithm_names()))
def test_exactly_the_limit_is_allowed_across_processes(name, redis_client, redis_url):
    prefix = f"test:{uuid.uuid4().hex}:"
    try:
        context = multiprocessing.get_context("spawn")
        with context.Pool(PROCESSES) as pool:
            counts = pool.map(hammer, [(name, prefix, redis_url)] * PROCESSES)
        assert sum(counts) == 100
    finally:
        for k in redis_client.scan_iter(f"{prefix}*"):
            redis_client.delete(k)
