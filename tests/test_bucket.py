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