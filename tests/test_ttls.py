"""Every key tokenguard writes must expire, so idle callers cost nothing."""

import uuid

import pytest

from tokenguard import Limit, MetricsRecorder, get_algorithm
from tokenguard.budget import DAY_TTL, MONTH_TTL, Budget, BudgetedBucket, Cost


@pytest.fixture
def prefix(redis_client):
    p = f"test:{uuid.uuid4().hex}:"
    yield p
    for key in redis_client.scan_iter(f"{p}*"):
        redis_client.delete(key)


def ttls(client, prefix):
    keys = list(client.scan_iter(f"{prefix}*"))
    assert keys, "the operation wrote nothing"
    return {key: client.ttl(key) for key in keys}


def test_every_algorithm_sets_a_ttl_that_matches_the_rule(redis_client, prefix):
    rule = Limit(capacity=60, refill_rate=1)  # a full bucket in 60 s
    expected = {
        "token_bucket": 120,  # twice the time to refill from empty
        "fixed_window": 61,  # one window, plus a second
        "sliding_window": 61,
    }
    for name, limit in expected.items():
        algo = get_algorithm(name, redis_client, key_prefix=f"{prefix}{name}:")
        algo.check("someone", 1, rule)
        for key, ttl in ttls(redis_client, f"{prefix}{name}:").items():
            assert 0 < ttl <= limit, (name, key, ttl)


def test_adjusting_a_bucket_keeps_the_ttl(redis_client, prefix):
    rule = Limit(capacity=60, refill_rate=1)
    for name in ("token_bucket", "fixed_window", "sliding_window"):
        algo = get_algorithm(name, redis_client, key_prefix=f"{prefix}{name}:")
        algo.check("someone", 10, rule)
        algo.adjust("someone", -5, rule)
        for key, ttl in ttls(redis_client, f"{prefix}{name}:").items():
            assert ttl > 0, (name, key)


def test_budget_keys_expire_too(redis_client, prefix):
    bucket = BudgetedBucket(
        redis_client,
        "owner",
        "b",
        capacity=1000,
        refill_rate=10,
        budget=Budget(daily_tokens=5000, monthly_tokens=50000),
        key_prefix=prefix,
    )
    bucket.charge(Cost(10))
    seen = ttls(redis_client, prefix)
    assert len(seen) == 3  # the burst bucket, the day and the month
    assert all(0 < ttl <= MONTH_TTL for ttl in seen.values())
    assert any(ttl <= 200 for ttl in seen.values())  # the burst bucket: minutes
    assert any(DAY_TTL - 60 < ttl <= DAY_TTL for ttl in seen.values())
    assert any(MONTH_TTL - 60 < ttl <= MONTH_TTL for ttl in seen.values())


def test_metrics_keys_expire_after_the_retention(redis_client, prefix):
    recorder = MetricsRecorder(redis_client, prefix, retention=300)
    recorder.record("api", "ip:1", allowed=False)
    recorder.record("api", "ip:1", allowed=True, tokens=3)
    seen = ttls(redis_client, prefix)
    assert len(seen) == 3
    assert all(0 < ttl <= 420 for ttl in seen.values())  # retention + 120
