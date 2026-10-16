"""The contract every algorithm must meet, run against all of them.

Add an algorithm to NAMES and it has to pass the same tests. Time is faked, so
nothing here sleeps. (Algorithm-specific behavior has its own test file.)
"""

import threading
import uuid

import pytest

from tokenguard import algorithms
from tokenguard.algorithms import Limit, algorithm_names, get_algorithm

NAMES = ["token_bucket", "fixed_window", "sliding_window"]
RULE = Limit(capacity=10, refill_rate=1)  # 10 at once, 1 per second (a 10s window)


@pytest.fixture(params=NAMES)
def algo(request, redis_client, clock):
    """Each algorithm on a fake clock, in its own key namespace."""
    prefix = f"test:{uuid.uuid4().hex}:"
    yield get_algorithm(request.param, redis_client, clock=clock, key_prefix=prefix)
    for k in redis_client.scan_iter(f"{prefix}*"):
        redis_client.delete(k)


@pytest.fixture(params=NAMES)
def live(request, redis_client):
    """Each algorithm on Redis's own clock, as in production."""
    prefix = f"test:{uuid.uuid4().hex}:"
    yield get_algorithm(request.param, redis_client, key_prefix=prefix)
    for k in redis_client.scan_iter(f"{prefix}*"):
        redis_client.delete(k)


# ---- the registry ----
def test_the_built_in_algorithms_are_registered():
    assert set(NAMES) <= set(algorithm_names())


def test_an_unknown_algorithm_name_is_an_error(redis_client):
    with pytest.raises(ValueError, match="unknown algorithm"):
        get_algorithm("sliding_log", redis_client)


def test_a_custom_algorithm_can_be_registered(redis_client):
    algorithms.register_algorithm("custom", lambda client, **kw: object())
    try:
        assert "custom" in algorithm_names()
        assert get_algorithm("custom", redis_client) is not None
    finally:
        algorithms._FACTORIES.pop("custom")


def test_the_limit_validates_its_numbers():
    with pytest.raises(ValueError):
        Limit(capacity=0, refill_rate=1)
    with pytest.raises(ValueError):
        Limit(capacity=10, refill_rate=0)
    assert Limit(capacity=60, refill_rate=2).window == 30


# ---- the contract ----
def test_allows_up_to_capacity_then_blocks(algo):
    assert all(algo.check("k", 1, RULE).allowed for _ in range(10))
    assert not algo.check("k", 1, RULE).allowed


def test_remaining_counts_down(algo):
    assert algo.check("k", 1, RULE).remaining == pytest.approx(9)
    assert algo.check("k", 3, RULE).remaining == pytest.approx(6)


def test_costs_add_up(algo):
    assert algo.check("k", 5, RULE).allowed
    assert not algo.check("k", 6, RULE).allowed
    assert algo.check("k", 5, RULE).allowed


def test_a_cost_above_capacity_can_never_fit(algo):
    d = algo.check("k", 11, RULE)
    assert not d.allowed
    assert d.retry_after == float("inf")


def test_a_blocked_check_spends_nothing(algo):
    algo.check("k", 8, RULE)
    assert not algo.check("k", 5, RULE).allowed
    assert algo.check("k", 2, RULE).allowed  # the 2 left are still there


def test_peek_reports_without_spending(algo):
    algo.check("k", 4, RULE)
    first = algo.peek("k", 6, RULE)
    assert first.allowed and first.remaining == pytest.approx(6)
    assert algo.peek("k", 6, RULE) == first  # nothing changed
    assert not algo.peek("k", 7, RULE).allowed


def test_a_zero_cost_is_always_free(algo):
    algo.check("k", 10, RULE)
    d = algo.check("k", 0, RULE)
    assert d.allowed and d.remaining == pytest.approx(0)


def test_keys_are_independent(algo):
    algo.check("a", 10, RULE)
    assert not algo.check("a", 1, RULE).allowed
    assert algo.check("b", 10, RULE).allowed


def test_a_blocked_caller_is_told_when_to_come_back(algo, clock):
    algo.check("k", 10, RULE)
    d = algo.check("k", 1, RULE)
    assert not d.allowed
    assert 0 < d.retry_after <= RULE.window
    clock.advance(d.retry_after + 1e-6)  # wait exactly as told
    assert algo.check("k", 1, RULE).allowed


def test_an_idle_key_gets_its_whole_allowance_back(algo, clock):
    algo.check("k", 10, RULE)
    clock.advance(1_000)
    assert algo.check("k", 10, RULE).allowed


def test_negative_costs_are_rejected(algo):
    with pytest.raises(ValueError):
        algo.check("k", -1, RULE)


# ---- settling an estimate (adjust) ----
def test_adjust_refunds_and_charges_the_difference(algo):
    algo.check("k", 8, RULE)  # estimate 8, 2 left
    assert algo.adjust("k", -5, RULE) == pytest.approx(7)  # really used 3
    assert algo.adjust("k", 2, RULE) == pytest.approx(5)  # really used 5
    assert algo.peek("k", 0, RULE).remaining == pytest.approx(5)


def test_a_refund_cannot_exceed_the_limit(algo):
    algo.check("k", 4, RULE)
    assert algo.adjust("k", -1_000, RULE) == pytest.approx(10)


def test_overspend_is_bounded(algo):
    assert algo.adjust("k", 1_000, RULE) == pytest.approx(-10)
    assert not algo.check("k", 1, RULE).allowed


# ---- concurrency: the whole point of doing it in Lua ----
def test_exactly_the_limit_is_allowed_under_concurrency(live):
    rule = Limit(capacity=100, refill_rate=0.01)  # a 10,000 second window
    allowed = []

    def hammer():
        for _ in range(20):
            allowed.append(live.check("k", 1, rule).allowed)

    threads = [threading.Thread(target=hammer) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(allowed) == 400
    assert sum(allowed) == 100
