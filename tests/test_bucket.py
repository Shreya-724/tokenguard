import pytest
import math

from tokenguard import FakeClock, TokenBucket


@pytest.fixture
def clock():
    return FakeClock()


def make(clock, capacity=10, rate=1):
    return TokenBucket(capacity, rate, clock=clock)


def test_starts_full(clock):
    b = make(clock)
    assert b.allow(10).allowed


def test_burst_then_rejected(clock):
    b = make(clock)
    assert all(b.allow().allowed for _ in range(10))
    assert not b.allow().allowed


def test_refills_after_n_seconds(clock):
    b = make(clock)
    b.allow(10)
    clock.advance(3)
    assert b.allow(3).allowed
    assert not b.allow().allowed


def test_never_exceeds_capacity(clock):
    b = make(clock)
    clock.advance(10_000)
    assert b.allow(10).allowed
    assert not b.allow(1).allowed


def test_fractional_refill(clock):
    b = make(clock, capacity=5, rate=0.5)
    b.allow(5)
    clock.advance(1)                 # 0.5 tokens
    assert not b.allow().allowed
    clock.advance(1)                 # 1.0 tokens
    assert b.allow().allowed


def test_cost_above_capacity_always_rejected(clock):
    assert make(clock).allow(11).allowed is False


def test_zero_cost_allowed_and_free(clock):
    b = make(clock)
    assert b.allow(0).allowed is True
    assert b.allow(10).allowed is True       # nothing was spent


def test_negative_cost_raises(clock):
    with pytest.raises(ValueError):
        make(clock).allow(-1)


def test_clock_going_backwards_adds_nothing(clock):
    clock.set(100)
    b = make(clock)
    b.allow(10)
    clock.set(50)
    assert not b.allow().allowed


@pytest.mark.parametrize("cap,rate", [(0, 1), (-1, 1), (1, 0), (1, -5)])
def test_invalid_constructor_args(cap, rate):
    with pytest.raises(ValueError):
        TokenBucket(cap, rate)


def test_retry_after_is_accurate(clock):
    b = make(clock, capacity=10, rate=2)
    b.allow(10)
    d = b.allow(4)                       # need 4 tokens at 2/sec → 2 seconds
    assert not d.allowed
    assert d.retry_after == pytest.approx(2.0)
    clock.advance(d.retry_after)
    assert b.allow(4).allowed            # waiting that long really works


def test_retry_after_zero_when_allowed(clock):
    assert make(clock).allow().retry_after == 0.0


def test_retry_after_infinite_when_cost_exceeds_capacity(clock):
    assert make(clock).allow(11).retry_after == math.inf


def test_peek_does_not_spend(clock):
    b = make(clock)
    for _ in range(5):
        b.peek(10)
    assert b.allow(10).allowed