"""Buffered metrics: same numbers as the synchronous recorder, fewer round trips."""

import time
import uuid

import pytest
import redis

from tokenguard import FakeClock
from tokenguard.metrics import MetricsReader, MetricsRecorder

T0 = 1_700_000_040  # a whole minute


@pytest.fixture
def prefix(redis_client):
    p = f"test:{uuid.uuid4().hex}:"
    yield p
    for k in redis_client.scan_iter(f"{p}*"):
        redis_client.delete(k)


@pytest.fixture
def clock():
    return FakeClock(T0)


def make(redis_client, prefix, clock, **options):
    # A long interval: the background thread never fires, the test flushes by hand.
    return MetricsRecorder(
        redis_client, prefix, clock=clock, flush_interval=3600, **options
    )


def traffic(rec, clock):
    for second in range(5):
        clock.set(T0 + second)
        for _ in range(4):
            rec.record("api", "ip:1", allowed=True, tokens=2)
        rec.record("api", "ip:2", allowed=False)
        rec.record("chat", "user:9", allowed=True, tokens=100)
    rec.record_adjust("chat", "user:9", -40)
    rec.record_adjust("chat", "user:9", 40)


def snapshot(reader):
    s = reader.summary(60)
    return (
        (s.allowed, s.blocked, round(s.tokens, 6)),
        [
            (c.scope, c.identity, round(c.tokens, 6), c.blocked)
            for c in reader.top_consumers()
        ],
        sorted((r.scope, r.allowed, r.blocked, r.tokens) for r in reader.routes()),
    )


def test_buffered_gives_the_same_numbers_as_synchronous(redis_client, clock):
    sync_prefix = f"test:{uuid.uuid4().hex}:"
    buf_prefix = f"test:{uuid.uuid4().hex}:"
    try:
        sync = MetricsRecorder(redis_client, sync_prefix, clock=clock)
        buffered = make(redis_client, buf_prefix, clock)
        traffic(sync, clock)
        traffic(buffered, clock)
        buffered.flush()
        clock.set(T0 + 10)
        a = snapshot(MetricsReader(redis_client, sync_prefix, clock=clock))
        b = snapshot(MetricsReader(redis_client, buf_prefix, clock=clock))
        assert a == b
        assert a[0][0] > 0 and a[0][1] == 5  # the comparison is not of two empties
    finally:
        for p in (sync_prefix, buf_prefix):
            for k in redis_client.scan_iter(f"{p}*"):
                redis_client.delete(k)


def test_nothing_reaches_redis_until_a_flush(redis_client, prefix, clock):
    rec = make(redis_client, prefix, clock)
    rec.record("api", "ip:1", allowed=True, tokens=1)
    assert rec.pending == 1
    assert list(redis_client.scan_iter(f"{prefix}*")) == []
    assert rec.flush() == 1
    assert rec.pending == 0
    assert list(redis_client.scan_iter(f"{prefix}*")) != []


def test_a_flush_merges_samples_of_the_same_second_and_consumer(
    redis_client, prefix, clock
):
    rec = make(redis_client, prefix, clock)
    calls = []
    real = rec._script

    def counting(*args, **kwargs):
        calls.append(kwargs["args"])
        return real(*args, **kwargs)

    rec._script = counting
    for _ in range(50):
        rec.record("api", "ip:1", allowed=True, tokens=1)
    rec.record("api", "ip:2", allowed=True, tokens=1)
    assert rec.flush() == 51
    assert len(calls) == 2  # 51 samples, two (second, consumer) pairs
    reader = MetricsReader(redis_client, prefix, clock=clock)
    assert reader.summary(60).allowed == 51


def test_the_background_thread_flushes_by_itself(redis_client, prefix, clock):
    rec = MetricsRecorder(redis_client, prefix, clock=clock, flush_interval=0.05)
    reader = MetricsReader(redis_client, prefix, clock=clock)
    try:
        rec.record("api", "ip:1", allowed=True, tokens=1)
        # `pending` hits 0 the moment the thread takes the batch, before Redis has
        # it, so wait for the result itself.
        deadline = time.time() + 5
        while reader.summary(60).allowed < 1 and time.time() < deadline:
            time.sleep(0.02)
        assert reader.summary(60).allowed == 1
        assert rec.pending == 0
    finally:
        rec.close()


def test_close_sends_what_is_left(redis_client, prefix, clock):
    rec = make(redis_client, prefix, clock)
    rec.record("api", "ip:1", allowed=True, tokens=1)
    rec.close()
    assert MetricsReader(redis_client, prefix, clock=clock).summary(60).allowed == 1
    rec.close()  # safe to repeat


def test_a_full_queue_drops_and_counts(redis_client, prefix, clock):
    rec = make(redis_client, prefix, clock, max_pending=3)
    for _ in range(5):
        rec.record("api", "ip:1", allowed=True, tokens=1)
    assert rec.pending == 3 and rec.dropped == 2
    rec.flush()
    assert MetricsReader(redis_client, prefix, clock=clock).summary(60).allowed == 3


def test_redis_down_drops_the_batch_and_never_raises(prefix, clock):
    dead = redis.Redis.from_url(
        "redis://127.0.0.1:1/0", socket_connect_timeout=0.2, socket_timeout=0.2
    )
    rec = MetricsRecorder(dead, prefix, clock=clock, flush_interval=3600)
    for _ in range(4):
        rec.record("api", "ip:1", allowed=True, tokens=1)
    assert rec.flush() == 0
    assert rec.dropped == 4 and rec.pending == 0


def test_record_itself_does_not_touch_redis(prefix, clock):
    dead = redis.Redis.from_url(
        "redis://127.0.0.1:1/0", socket_connect_timeout=0.2, socket_timeout=0.2
    )
    rec = MetricsRecorder(dead, prefix, clock=clock, flush_interval=3600)
    start = time.perf_counter()
    for _ in range(100):
        rec.record("api", "ip:1", allowed=True, tokens=1)
    assert time.perf_counter() - start < 0.2  # 100 dead round trips would take 20 s
    assert rec.dropped == 0 and rec.pending == 100


def test_flush_interval_and_max_pending_are_validated(redis_client):
    with pytest.raises(ValueError):
        MetricsRecorder(redis_client, flush_interval=-1)
    with pytest.raises(ValueError):
        MetricsRecorder(redis_client, max_pending=0)


def test_default_is_still_synchronous(redis_client, prefix, clock):
    rec = MetricsRecorder(redis_client, prefix, clock=clock)
    rec.record("api", "ip:1", allowed=True, tokens=1)
    assert rec.pending == 0
    assert MetricsReader(redis_client, prefix, clock=clock).summary(60).allowed == 1
