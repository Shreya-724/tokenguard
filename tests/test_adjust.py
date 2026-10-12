import pytest


def test_refund_when_actual_is_below_estimate(make_adjustable, clock):
    b = make_adjustable(clock, capacity=2000, rate=1)
    assert b.allow(1000).allowed  # estimate: 1,000 tokens
    before = b.peek(0).remaining
    b.adjust(600 - 1000)  # the model really used 600
    assert b.peek(0).remaining - before == pytest.approx(400)


def test_extra_charge_when_actual_is_above_estimate(make_adjustable, clock):
    b = make_adjustable(clock, capacity=2000, rate=1)
    b.allow(500)
    assert b.adjust(800 - 500) == pytest.approx(2000 - 800)


def test_refund_cannot_exceed_capacity(make_adjustable, clock):
    b = make_adjustable(clock, capacity=100, rate=1)
    b.allow(10)
    assert b.adjust(-1000) == pytest.approx(100)


def test_overspend_goes_into_bounded_debt(make_adjustable, clock):
    b = make_adjustable(clock, capacity=100, rate=1)
    b.allow(100)  # bucket empty
    assert b.adjust(30) == pytest.approx(-30)  # used 30 more than charged
    d = b.allow(1)
    assert not d.allowed
    assert d.retry_after == pytest.approx(31)  # 30 to repay the debt + 1 for the call


def test_debt_is_capped_at_minus_capacity(make_adjustable, clock):
    b = make_adjustable(clock, capacity=100, rate=1)
    assert b.adjust(10_000) == pytest.approx(-100)


def test_debt_is_repaid_by_refill(make_adjustable, clock):
    b = make_adjustable(clock, capacity=100, rate=1)
    b.allow(100)
    b.adjust(30)  # -30
    clock.advance(40)  # +40 -> 10
    assert b.allow(10).allowed


def test_zero_adjustment_changes_nothing(make_adjustable, clock):
    b = make_adjustable(clock, capacity=100, rate=1)
    b.allow(40)
    assert b.adjust(0) == pytest.approx(60)


def test_adjust_includes_time_that_passed(make_adjustable, clock):
    b = make_adjustable(clock, capacity=100, rate=2)
    b.allow(100)
    clock.advance(10)  # +20 refilled
    assert b.adjust(-5) == pytest.approx(25)


def test_adjust_on_a_fresh_bucket_assumes_full(make_adjustable, clock):
    b = make_adjustable(clock, capacity=100, rate=1)
    assert b.adjust(-50) == pytest.approx(100)
    assert b.adjust(30) == pytest.approx(70)


def test_large_costs_drain_in_proportion(make_adjustable, clock):
    small = make_adjustable(clock, capacity=100_000, rate=1)
    huge = make_adjustable(clock, capacity=100_000, rate=1)
    assert small.allow(50).remaining == 99_950
    assert huge.allow(50_000).remaining == 50_000


def test_cost_above_capacity_is_rejected_with_infinite_retry(make_adjustable, clock):
    d = make_adjustable(clock, capacity=100, rate=1).allow(101)
    assert not d.allowed and d.retry_after == float("inf")
