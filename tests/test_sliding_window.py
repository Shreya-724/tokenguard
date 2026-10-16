"""Sliding window (a log of recent requests): exact, with no edge to exploit."""

import uuid

import pytest

from tokenguard.algorithms import Limit, SlidingWindowAlgorithm, get_algorithm

RULE = Limit(capacity=10, refill_rate=1)  # at most 10 in ANY 10 seconds


@pytest.fixture
def prefix(redis_client):
    p = f"test:{uuid.uuid4().hex}:"
    yield p
    for k in redis_client.scan_iter(f"{p}*"):
        redis_client.delete(k)


@pytest.fixture
def sw(redis_client, clock, prefix):
    return SlidingWindowAlgorithm(redis_client, clock=clock, key_prefix=prefix)


def burst(algo, count, cost=1):
    """How many of `count` back-to-back requests get through."""
    return sum(algo.check("user", cost, RULE).allowed for _ in range(count))


def max_in_any_window(times, window):
    """The most events inside any span of `window` seconds (start excluded)."""
    best, start = 0, 0
    for end, t in enumerate(times):
        while t - times[start] >= window:
            start += 1
        best = max(best, end - start + 1)
    return best


def edge_attacker(algo, clock, rule=RULE):
    """Send 20 requests just before each window edge and 20 just after it."""
    allowed = []
    for edge in range(10, 60, 10):
        for moment in (edge - 0.1, edge):
            clock.set(moment)
            for _ in range(20):
                if algo.check("user", 1, rule).allowed:
                    allowed.append(clock.now())
    return allowed


# ---- the boundary problem is gone ----
def test_no_double_burst_across_a_window_edge(sw, clock):
    clock.set(9.9)
    assert burst(sw, 10) == 10
    clock.set(10.0)  # the spot where a fixed window resets and lets 10 more in
    assert burst(sw, 10) == 0


def test_never_more_than_the_limit_in_any_window_length_span(sw, clock):
    allowed = edge_attacker(sw, clock)
    assert allowed  # it let traffic through...
    assert max_in_any_window(allowed, RULE.window) <= 10  # ...but never too much


def test_a_fixed_window_does_exceed_it_under_the_same_attack(
    redis_client, clock, prefix
):
    fixed = get_algorithm("fixed_window", redis_client, clock, prefix)
    allowed = edge_attacker(fixed, clock)
    assert max_in_any_window(allowed, RULE.window) == 20  # twice the limit


# ---- exact windows and hints ----
def test_an_entry_exactly_one_window_old_is_free_again(sw, clock):
    clock.set(0)
    burst(sw, 10)
    clock.set(9.999)
    assert not sw.check("user", 1, RULE).allowed
    clock.set(10.0)
    assert sw.check("user", 1, RULE).allowed


def test_retry_after_is_the_exact_moment_enough_has_expired(sw, clock):
    clock.set(0)
    sw.check("user", 5, RULE)
    clock.set(4)
    sw.check("user", 5, RULE)
    clock.set(5)
    blocked = sw.check("user", 6, RULE)  # needs 6 free: both entries must expire
    assert not blocked.allowed
    assert blocked.retry_after == pytest.approx(9)  # the second one frees at t=14
    clock.set(13.999)
    assert not sw.check("user", 6, RULE).allowed
    clock.set(14.0)
    assert sw.check("user", 6, RULE).allowed


def test_a_small_request_only_waits_for_the_first_entry(sw, clock):
    clock.set(0)
    sw.check("user", 5, RULE)
    clock.set(4)
    sw.check("user", 5, RULE)
    clock.set(5)
    assert sw.check("user", 5, RULE).retry_after == pytest.approx(5)  # t=10


def test_reset_after_is_when_the_newest_entry_expires(sw, clock):
    clock.set(0)
    sw.check("user", 1, RULE)
    clock.set(3)
    assert sw.peek("user", 1, RULE).reset_after == pytest.approx(7)
    assert sw.check("user", 1, RULE).reset_after == pytest.approx(10)


def test_fractional_costs_add_up_without_rounding_trouble(sw):
    rule = Limit(capacity=1, refill_rate=0.001)
    assert sum(sw.check("u", 0.1, rule).allowed for _ in range(12)) == 10


# ---- settling an estimate ----
def test_a_refund_shrinks_the_newest_entries_first(sw, clock):
    clock.set(0)
    sw.check("user", 4, RULE)
    clock.set(1)
    sw.check("user", 3, RULE)
    assert sw.adjust("user", -5, RULE) == pytest.approx(8)  # 3 gone, 2 off the 4
    clock.set(10)  # the (reduced) first entry expires on its own schedule
    assert sw.peek("user", 0, RULE).remaining == pytest.approx(10)


def test_an_extra_charge_grows_the_newest_entry(sw, clock):
    clock.set(0)
    sw.check("user", 3, RULE)
    assert sw.adjust("user", 2, RULE) == pytest.approx(5)


def test_adjust_with_nothing_live_charges_a_fresh_entry(sw, clock):
    assert sw.adjust("user", 4, RULE) == pytest.approx(6)


# ---- what is stored ----
def test_one_entry_per_spending_request_whatever_its_cost(
    sw, redis_client, prefix, clock
):
    big = Limit(capacity=10_000, refill_rate=1)
    clock.set(0)
    sw.check("user", 5_000, big)  # one 5,000-token request is one entry
    sw.check("user", 2.5, big)
    sw.check("user", 0, big)  # free: nothing stored
    key = f"{prefix}sw:user"
    assert redis_client.zcard(key) == 2
    members = redis_client.zrange(key, 0, -1)
    assert sorted(float(m.rsplit(":", 1)[1]) for m in members) == [2.5, 5_000]


def test_requests_at_the_same_instant_do_not_overwrite_each_other(
    sw, redis_client, prefix, clock
):
    clock.set(5)
    burst(sw, 10)
    assert redis_client.zcard(f"{prefix}sw:user") == 10


def test_old_entries_are_cleaned_up_as_new_ones_arrive(sw, redis_client, prefix, clock):
    for second in range(60):
        clock.set(second)
        sw.check("user", 1, RULE)
    assert redis_client.zcard(f"{prefix}sw:user") <= 11  # never grows without bound


def test_the_key_expires_when_idle(sw, redis_client, prefix, clock):
    clock.set(0)
    sw.check("user", 1, RULE)
    assert 0 < redis_client.pttl(f"{prefix}sw:user") <= 11_000


def test_a_peek_or_a_blocked_check_writes_nothing(sw, redis_client, prefix, clock):
    clock.set(0)
    burst(sw, 10)
    sw.peek("user", 1, RULE)
    sw.check("user", 1, RULE)  # blocked
    assert redis_client.zcard(f"{prefix}sw:user") == 10
