"""Fixed window: how it works, and the boundary problem it cannot avoid."""

import uuid

import pytest

from tokenguard.algorithms import FixedWindowAlgorithm, Limit, get_algorithm

RULE = Limit(capacity=10, refill_rate=1)  # 10 per 10 second window


@pytest.fixture
def prefix(redis_client):
    p = f"test:{uuid.uuid4().hex}:"
    yield p
    for k in redis_client.scan_iter(f"{p}*"):
        redis_client.delete(k)


@pytest.fixture
def fw(redis_client, clock, prefix):
    return FixedWindowAlgorithm(redis_client, clock=clock, key_prefix=prefix)


def burst(algo, count, cost=1):
    """How many of `count` back-to-back requests get through."""
    return sum(algo.check("user", cost, RULE).allowed for _ in range(count))


# ---- the boundary problem ----
def test_a_fixed_window_allows_twice_the_limit_across_a_window_edge(fw, clock):
    clock.set(9.9)  # 0.1s before the window ends
    assert burst(fw, 10) == 10  # the whole quota, used up
    clock.set(10.0)  # a new window starts, and the counter is zero again
    assert burst(fw, 10) == 10  # the whole quota again, 0.1 seconds later
    # 20 requests in 0.1 seconds, though the limit is "10 per 10 seconds"


def test_a_token_bucket_does_not_have_that_burst(redis_client, clock, prefix):
    bucket = get_algorithm("token_bucket", redis_client, clock, prefix)
    clock.set(9.9)
    assert burst(bucket, 10) == 10
    clock.set(10.0)  # 0.1s later only 0.1 token has refilled
    assert burst(bucket, 10) == 0


# ---- how the window works ----
def test_the_counter_resets_exactly_at_the_window_edge(fw, clock):
    clock.set(0)
    assert burst(fw, 10) == 10
    clock.set(9.999)
    assert not fw.check("user", 1, RULE).allowed
    clock.set(10.0)
    assert fw.check("user", 1, RULE).allowed


def test_retry_after_and_reset_after_point_at_the_window_end(fw, clock):
    clock.set(3.5)
    burst(fw, 10)
    blocked = fw.check("user", 1, RULE)
    assert blocked.retry_after == pytest.approx(6.5)
    assert blocked.reset_after == pytest.approx(6.5)


def test_reset_after_is_reported_when_allowed_too(fw, clock):
    clock.set(4.0)
    assert fw.check("user", 1, RULE).reset_after == pytest.approx(6.0)


def test_the_window_length_is_capacity_over_refill_rate(fw, clock):
    rule = Limit(capacity=60, refill_rate=2)  # 60 per 30 seconds
    clock.set(0)
    assert all(fw.check("u", 1, rule).allowed for _ in range(60))
    clock.set(29.9)
    assert not fw.check("u", 1, rule).allowed
    clock.set(30.0)
    assert fw.check("u", 1, rule).allowed


def test_fractional_costs_add_up_without_rounding_trouble(fw):
    rule = Limit(capacity=1, refill_rate=0.001)
    assert sum(fw.check("u", 0.1, rule).allowed for _ in range(12)) == 10


def test_a_refund_after_the_window_rolled_over_changes_nothing(fw, clock):
    clock.set(5)
    fw.check("user", 8, RULE)
    clock.set(12)  # the next window; its counter is empty
    assert fw.adjust("user", -5, RULE) == pytest.approx(10)
    assert fw.check("user", 10, RULE).allowed


# ---- what is stored ----
def test_state_is_one_small_hash_that_expires(fw, redis_client, prefix, clock):
    clock.set(0)
    fw.check("user", 3, RULE)
    key = f"{prefix}fw:user"
    state = redis_client.hgetall(key)
    assert set(state) == {"count", "idx"}
    assert float(state["count"]) == 3 and int(state["idx"]) == 0
    assert 0 < redis_client.ttl(key) <= 11  # window + 1 second


def test_a_blocked_or_free_check_writes_nothing(fw, redis_client, prefix, clock):
    clock.set(0)
    fw.check("user", 0, RULE)
    assert not redis_client.exists(f"{prefix}fw:user")
    fw.peek("user", 1, RULE)
    assert not redis_client.exists(f"{prefix}fw:user")


def test_fixed_window_keys_do_not_collide_with_the_token_bucket(
    fw, redis_client, clock, prefix
):
    bucket = get_algorithm("token_bucket", redis_client, clock, prefix)
    bucket.check("user", 10, RULE)
    assert fw.check("user", 10, RULE).allowed  # its own, untouched counter
