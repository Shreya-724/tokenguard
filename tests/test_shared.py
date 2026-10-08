import math

import pytest


# ---- core behavior ----
def test_starts_full(make, clock):
    assert make(clock).peek(10).allowed


def test_burst_then_rejected(make, clock):
    b = make(clock)
    assert all(b.allow().allowed for _ in range(10))
    assert not b.allow().allowed


def test_refills_after_n_seconds(make, clock):
    b = make(clock)
    for _ in range(10):
        b.allow()
    clock.advance(3)
    assert b.allow(3).allowed
    assert not b.allow().allowed


def test_never_exceeds_capacity(make, clock):
    b = make(clock)
    clock.advance(10_000)
    assert b.peek().remaining == 10
    assert not b.allow(11).allowed


# ---- edge cases ----
def test_fractional_refill(make, clock):
    b = make(clock, capacity=5, rate=0.5)
    b.allow(5)
    clock.advance(1)
    assert b.peek().remaining == pytest.approx(0.5)
    assert not b.allow().allowed
    clock.advance(1)
    assert b.allow().allowed


def test_cost_above_capacity_always_rejected(make, clock):
    d = make(clock).allow(11)
    assert not d.allowed
    assert d.retry_after == math.inf


def test_zero_cost_allowed_and_free(make, clock):
    b = make(clock)
    assert b.allow(0).allowed
    assert b.peek().remaining == 10


def test_negative_cost_raises(make, clock):
    with pytest.raises(ValueError):
        make(clock).allow(-1)


def test_clock_going_backwards_adds_nothing(make, clock):
    clock.set(100)
    b = make(clock)
    b.allow(10)
    clock.set(50)
    assert b.peek().remaining == 0


@pytest.mark.parametrize("cap,rate", [(0, 1), (-1, 1), (1, 0), (1, -5)])
def test_invalid_constructor_args(make, clock, cap, rate):
    with pytest.raises(ValueError):
        make(clock, cap, rate)


# ---- Decision / retry_after / peek ----
def test_retry_after_is_accurate(make, clock):
    b = make(clock, capacity=10, rate=2)
    b.allow(10)
    d = b.allow(4)
    assert not d.allowed
    assert d.retry_after == pytest.approx(2.0)
    clock.advance(d.retry_after)
    assert b.allow(4).allowed


def test_retry_after_zero_when_allowed(make, clock):
    assert make(clock).allow().retry_after == 0.0


def test_retry_after_infinite_when_cost_exceeds_capacity(make, clock):
    assert make(clock).allow(11).retry_after == math.inf


def test_peek_does_not_spend(make, clock):
    b = make(clock)
    for _ in range(5):
        b.peek(10)
    assert b.allow(10).allowed
