import pytest

from tokenguard import FakeClock, TokenBucket


@pytest.fixture
def clock():
    return FakeClock()


def make(clock, capacity=10, rate=1):
    return TokenBucket(capacity, rate, clock=clock)


def test_starts_full(clock):
    b = make(clock)
    assert b.allow(10) is True


def test_burst_then_rejected(clock):
    b = make(clock)
    assert all(b.allow() for _ in range(10))
    assert b.allow() is False


def test_refills_after_n_seconds(clock):
    b = make(clock)
    b.allow(10)
    clock.advance(3)
    assert b.allow(3) is True
    assert b.allow() is False


def test_never_exceeds_capacity(clock):
    b = make(clock)
    clock.advance(10_000)
    assert b.allow(10) is True
    assert b.allow(1) is False


def test_fractional_refill(clock):
    b = make(clock, capacity=5, rate=0.5)
    b.allow(5)
    clock.advance(1)                 # 0.5 tokens
    assert b.allow() is False
    clock.advance(1)                 # 1.0 tokens
    assert b.allow() is True


def test_cost_above_capacity_always_rejected(clock):
    assert make(clock).allow(11) is False


def test_zero_cost_allowed_and_free(clock):
    b = make(clock)
    assert b.allow(0) is True
    assert b.allow(10) is True       # nothing was spent


def test_negative_cost_raises(clock):
    with pytest.raises(ValueError):
        make(clock).allow(-1)


def test_clock_going_backwards_adds_nothing(clock):
    clock.set(100)
    b = make(clock)
    b.allow(10)
    clock.set(50)
    assert b.allow() is False


@pytest.mark.parametrize("cap,rate", [(0, 1), (-1, 1), (1, 0), (1, -5)])
def test_invalid_constructor_args(cap, rate):
    with pytest.raises(ValueError):
        TokenBucket(cap, rate)