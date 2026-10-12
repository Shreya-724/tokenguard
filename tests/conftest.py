import os
import uuid

import pytest
import redis

from tokenguard import FakeClock, NaiveRedisTokenBucket, RedisTokenBucket, TokenBucket

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


def _build_factory(request, impl):
    """Return factory(clock, capacity, rate) building a bucket of one implementation."""
    if impl == "memory":
        return lambda clock, capacity=10, rate=1: TokenBucket(
            capacity, rate, clock=clock
        )

    client = request.getfixturevalue("redis_client")
    keys: list[str] = []

    def factory(clock, capacity=10, rate=1):
        k = f"test:{uuid.uuid4().hex}"
        keys.append(k)
        cls = NaiveRedisTokenBucket if impl == "naive" else RedisTokenBucket
        return cls(client, k, capacity, rate, clock=clock, key_prefix="")

    request.addfinalizer(lambda: keys and client.delete(*keys))
    return factory


@pytest.fixture(params=["memory", "naive", "lua"])
def make(request):
    """Every implementation: used by the shared behavior tests."""
    return _build_factory(request, request.param)


@pytest.fixture(params=["memory", "lua"])
def make_adjustable(request):
    """Implementations that support adjust() (the naive one deliberately doesn't)."""
    return _build_factory(request, request.param)
