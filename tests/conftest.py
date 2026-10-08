import os
import uuid

import pytest
import redis

from tokenguard import FakeClock, NaiveRedisTokenBucket, TokenBucket

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture(scope="session")
def redis_url():
    return REDIS_URL


@pytest.fixture(scope="session")
def redis_client():
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError:
        if os.getenv("CI"):  # in CI a missing Redis is a failure, not a skip
            pytest.fail("Redis must be available in CI")
        pytest.skip("Redis not running (start it with: docker compose up -d)")
    return client


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def key(redis_client):
    k = f"test:{uuid.uuid4().hex}"
    yield k
    redis_client.delete(k)


@pytest.fixture(params=["memory", "naive"])  # Day 4: add "lua"
def make(request):
    """Factory building a bucket of each implementation: make(clock, cap, rate)."""
    impl = request.param
    if impl == "memory":
        return lambda clock, capacity=10, rate=1: TokenBucket(
            capacity, rate, clock=clock
        )

    client = request.getfixturevalue("redis_client")
    keys: list[str] = []

    def factory(clock, capacity=10, rate=1):
        k = f"test:{uuid.uuid4().hex}"
        keys.append(k)
        cls = NaiveRedisTokenBucket  # Day 4: pick RedisTokenBucket when impl == "lua"
        return cls(client, k, capacity, rate, clock=clock, key_prefix="")

    request.addfinalizer(lambda: keys and client.delete(*keys))
    return factory
