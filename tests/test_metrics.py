"""Metrics: recording every decision, and reading it back."""

import uuid

import pytest
import redis

from tokenguard import FakeClock
from tokenguard.algorithms import Limit
from tokenguard.metrics import MetricsReader, MetricsRecorder

T0 = 1_700_000_040  # a whole minute (divisible by 60): easy to reason about
assert T0 % 60 == 0


@pytest.fixture
def prefix(redis_client):
    p = f"test:{uuid.uuid4().hex}:"
    yield p
    for k in redis_client.scan_iter(f"{p}*"):
        redis_client.delete(k)


@pytest.fixture
def clock():
    return FakeClock(T0)


@pytest.fixture
def rec(redis_client, prefix, clock):
    return MetricsRecorder(redis_client, prefix, clock=clock)


@pytest.fixture
def rd(redis_client, prefix, clock):
    return MetricsReader(redis_client, prefix, clock=clock)


# ---- recording and summary ----
def test_nothing_recorded_means_zeroes(rd):
    s = rd.summary(60)
    assert (s.allowed, s.blocked, s.tokens, s.blocked_ratio) == (0, 0, 0, 0.0)
    assert s.requests_per_second == 0.0
    assert rd.top_consumers() == []
    assert rd.routes() == []


def test_allowed_and_blocked_are_counted(rec, rd):
    for _ in range(3):
        rec.record("api", "ip:1", allowed=True, tokens=1)
    rec.record("api", "ip:1", allowed=False, tokens=1)
    s = rd.summary(60)
    assert (s.allowed, s.blocked, s.requests) == (3, 1, 4)
    assert s.blocked_ratio == pytest.approx(0.25)
    assert s.requests_per_second == pytest.approx(4 / 60)


def test_only_allowed_requests_spend_tokens(rec, rd):
    rec.record("chat", "u1", allowed=True, tokens=350)
    rec.record("chat", "u1", allowed=False, tokens=900)  # turned away: not spent
    assert rd.summary(60).tokens == 350


def test_fractional_tokens_add_up(rec, rd):
    for _ in range(3):
        rec.record("chat", "u1", allowed=True, tokens=0.1)
    assert rd.summary(60).tokens == pytest.approx(0.3)


def test_the_summary_dict_is_json_ready(rec, rd):
    rec.record("api", "ip:1", allowed=True, tokens=1)
    d = rd.summary(60).as_dict()
    assert d["requests"] == 1 and d["blocked_ratio"] == 0.0


# ---- time series ----
def test_timeseries_places_counts_in_the_right_second(rec, rd, clock):
    rec.record("api", "ip:1", allowed=True, tokens=1)  # at T0
    clock.advance(2)
    rec.record("api", "ip:1", allowed=False)
    rec.record("api", "ip:1", allowed=False)  # at T0 + 2
    points = rd.timeseries(seconds=5)
    assert [p.ts for p in points] == [T0 - 2, T0 - 1, T0, T0 + 1, T0 + 2]
    assert [(p.allowed, p.blocked) for p in points] == [
        (0, 0),
        (0, 0),
        (1, 0),
        (0, 0),
        (0, 2),
    ]


def test_timeseries_is_zero_filled_and_oldest_first(rd):
    points = rd.timeseries(seconds=120)
    assert len(points) == 120
    assert [p.ts for p in points] == sorted(p.ts for p in points)
    assert all(p.requests == 0 for p in points)


def test_timeseries_crosses_a_minute_boundary(rec, rd, clock):
    clock.set(T0 + 59)
    rec.record("api", "ip:1", allowed=True, tokens=1)
    clock.set(T0 + 60)
    rec.record("api", "ip:1", allowed=True, tokens=1)
    points = rd.timeseries(seconds=3)
    assert [(p.ts, p.allowed) for p in points] == [
        (T0 + 58, 0),
        (T0 + 59, 1),
        (T0 + 60, 1),
    ]


def test_step_groups_seconds(rec, rd, clock):
    for i in range(10):
        clock.set(T0 + i)
        rec.record("api", "ip:1", allowed=True, tokens=2)
    clock.set(T0 + 9)
    points = rd.timeseries(seconds=10, step=5)
    assert [(p.allowed, p.tokens) for p in points] == [(5, 10), (5, 10)]


def test_old_data_falls_out_of_the_window(rec, rd, clock):
    rec.record("api", "ip:1", allowed=True, tokens=1)
    clock.advance(30)
    assert rd.summary(60).allowed == 1
    assert rd.summary(10).allowed == 0  # 30 seconds ago is outside the last 10


def test_the_window_edge_is_exact(rec, rd, clock):
    rec.record("api", "ip:1", allowed=True, tokens=1)
    clock.advance(9)
    assert rd.summary(10).allowed == 1  # the last 10 seconds include T0
    clock.advance(1)
    assert rd.summary(10).allowed == 0


def test_bad_windows_are_rejected(rd):
    with pytest.raises(ValueError):
        rd.timeseries(seconds=0)
    with pytest.raises(ValueError):
        rd.timeseries(seconds=10, step=0)
    with pytest.raises(ValueError):
        rd.top_consumers(by="requests")
    with pytest.raises(ValueError):
        rd.top_consumers(minutes=0)


def test_a_window_longer_than_retention_is_clamped(redis_client, prefix, clock):
    reader = MetricsReader(redis_client, prefix, retention=120, clock=clock)
    assert len(reader.timeseries(seconds=10_000)) == 120


# ---- who is using the most ----
def test_top_consumers_ranks_by_tokens(rec, rd):
    rec.record("chat", "alice", allowed=True, tokens=100)
    rec.record("chat", "bob", allowed=True, tokens=900)
    rec.record("chat", "alice", allowed=True, tokens=300)
    top = rd.top_consumers(n=5)
    assert [(c.identity, c.tokens) for c in top] == [("bob", 900), ("alice", 400)]
    assert top[0].scope == "chat" and top[0].key == "chat:bob"


def test_top_consumers_respects_n(rec, rd):
    for i in range(6):
        rec.record("api", f"ip:{i}", allowed=True, tokens=i + 1)
    assert [c.identity for c in rd.top_consumers(n=2)] == ["ip:5", "ip:4"]


def test_top_consumers_by_blocked(rec, rd):
    rec.record("api", "polite", allowed=True, tokens=50)
    for _ in range(4):
        rec.record("api", "noisy", allowed=False)
    rec.record("api", "noisy", allowed=True, tokens=1)
    top = rd.top_consumers(by="blocked")
    assert [(c.identity, c.blocked) for c in top] == [("noisy", 4)]
    assert top[0].tokens == 1


def test_top_consumers_adds_up_several_minutes(rec, rd, clock):
    rec.record("api", "ip:1", allowed=True, tokens=5)
    clock.advance(60)
    rec.record("api", "ip:1", allowed=True, tokens=7)
    assert rd.top_consumers(minutes=1)[0].tokens == 7
    assert rd.top_consumers(minutes=2)[0].tokens == 12


def test_identities_with_colons_come_back_whole(rec, rd):
    rec.record("api", "ip:10.0.0.1", allowed=True, tokens=1)
    c = rd.top_consumers()[0]
    assert (c.scope, c.identity, c.key) == ("api", "ip:10.0.0.1", "api:ip:10.0.0.1")


def test_a_correction_changes_the_totals(rec, rd):
    rec.record("chat", "u1", allowed=True, tokens=1000)  # the estimate
    rec.record_adjust("chat", "u1", -600)  # really used 400
    assert rd.top_consumers()[0].tokens == 400
    assert rd.summary(60).tokens == 400


def test_a_fully_refunded_consumer_leaves_the_list(rec, rd):
    rec.record("chat", "u1", allowed=True, tokens=1000)
    rec.record_adjust("chat", "u1", -1000)
    assert rd.top_consumers() == []


def test_a_zero_correction_writes_nothing(rec, rd, redis_client, prefix):
    rec.record_adjust("chat", "u1", 0)
    assert list(redis_client.scan_iter(f"{prefix}*")) == []


def test_the_busiest_consumers_survive_a_full_list(redis_client, prefix, clock):
    rec = MetricsRecorder(redis_client, prefix, max_consumers=3, clock=clock)
    rd = MetricsReader(redis_client, prefix, clock=clock)
    rec.record("api", "whale", allowed=True, tokens=1000)
    for i in range(20):
        rec.record("api", f"minnow{i}", allowed=True, tokens=1)
    top = rd.top_consumers(n=10)
    assert top[0].identity == "whale"
    assert len(top) <= 3


# ---- per route ----
def test_routes_are_broken_down(rec, rd):
    for _ in range(3):
        rec.record("login", "ip:1", allowed=True, tokens=1)
    rec.record("login", "ip:1", allowed=False)
    rec.record("chat", "u1", allowed=True, tokens=500)
    routes = rd.routes()
    assert [r.scope for r in routes] == ["login", "chat"]  # busiest first
    login = routes[0]
    assert (login.allowed, login.blocked, login.blocked_ratio) == (3, 1, 0.25)
    assert routes[1].tokens == 500


def test_a_scope_with_colons_is_not_mangled(rec, rd):
    rec.record("^/api/v1:chat", "u1", allowed=True, tokens=3)
    (route,) = rd.routes()
    assert route.scope == "^/api/v1:chat" and route.tokens == 3


def test_a_numeric_scope_is_not_mistaken_for_a_second(rec, rd):
    rec.record("12", "u1", allowed=True, tokens=3)
    assert rd.summary(60).allowed == 1
    assert [r.scope for r in rd.routes()] == ["12"]


# ---- retention and robustness ----
def test_every_key_expires(rec, redis_client, prefix):
    rec.record("api", "ip:1", allowed=False)
    rec.record("api", "ip:1", allowed=True, tokens=1)
    keys = list(redis_client.scan_iter(f"{prefix}*"))
    assert len(keys) == 3  # the minute hash and two rankings
    for k in keys:
        ttl = redis_client.ttl(k)
        assert 0 < ttl <= 3600 + 120


def test_retention_is_configurable(redis_client, prefix, clock):
    rec = MetricsRecorder(redis_client, prefix, retention=300, clock=clock)
    rec.record("api", "ip:1", allowed=True, tokens=1)
    k = next(redis_client.scan_iter(f"{prefix}metrics:{T0 // 60}"))
    assert redis_client.ttl(k) <= 420


def test_settings_are_validated(redis_client, prefix):
    with pytest.raises(ValueError):
        MetricsRecorder(redis_client, prefix, retention=10)
    with pytest.raises(ValueError):
        MetricsRecorder(redis_client, prefix, max_consumers=0)


def test_recording_never_raises_when_redis_fails(rec, rd):
    def boom(**kwargs):
        raise redis.ConnectionError("pretend Redis is down")

    rec._script = boom
    rec.record("api", "ip:1", allowed=True, tokens=1)  # must not raise
    rec.record_adjust("api", "ip:1", 5)
    assert rec.dropped == 2
    assert rd.summary(60).requests == 0


def test_the_recorder_and_the_limiter_do_not_share_keys(rec, redis_client, prefix):
    rec.record("api", "ip:1", allowed=True, tokens=1)
    assert all(
        k.startswith(f"{prefix}metrics:") for k in redis_client.scan_iter(f"{prefix}*")
    )


# ---- the bucket level of one key ----
def test_bucket_level_of_a_new_key_is_full(rd):
    level = rd.bucket_level("api", "ip:9", Limit(10, 1))
    assert (level.remaining, level.capacity, level.used) == (10, 10, 0)


def test_bucket_level_reflects_what_was_spent_and_does_not_spend(
    rd, redis_client, prefix
):
    from tokenguard.algorithms import get_algorithm

    limit = Limit(10, 0.001)
    algo = get_algorithm("token_bucket", redis_client, key_prefix=prefix)
    algo.check("api:ip:1", 4, limit)
    first = rd.bucket_level("api", "ip:1", limit)
    second = rd.bucket_level("api", "ip:1", limit)
    assert first.remaining == pytest.approx(6, abs=0.1)
    assert second.remaining == pytest.approx(first.remaining, abs=0.1)
    assert first.reset_after == pytest.approx(4 / 0.001, rel=0.05)
    assert first.as_dict()["used"] == pytest.approx(4, abs=0.1)


@pytest.mark.parametrize("name", ["fixed_window", "sliding_window"])
def test_bucket_level_works_for_every_algorithm(rd, redis_client, prefix, name):
    from tokenguard.algorithms import get_algorithm

    limit = Limit(5, 0.001)
    algo = get_algorithm(name, redis_client, key_prefix=prefix)
    algo.check("api:ip:1", 2, limit)
    level = rd.bucket_level("api", "ip:1", limit, algorithm=name)
    assert level.algorithm == name and level.remaining == pytest.approx(3)
