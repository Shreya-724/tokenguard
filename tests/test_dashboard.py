"""The dashboard snapshot: one JSON-ready dict with everything a screen needs."""

import json
import uuid

import pytest

from tokenguard import FakeClock
from tokenguard.dashboard import snapshot
from tokenguard.metrics import MetricsReader, MetricsRecorder

T0 = 1_700_000_040


@pytest.fixture
def prefix(redis_client):
    p = f"test:{uuid.uuid4().hex}:"
    yield p
    for k in redis_client.scan_iter(f"{p}*"):
        redis_client.delete(k)


@pytest.fixture
def pair(redis_client, prefix):
    clock = FakeClock(T0)
    return (
        MetricsRecorder(redis_client, prefix, clock=clock),
        MetricsReader(redis_client, prefix, clock=clock),
        clock,
    )


def test_an_empty_snapshot_has_every_part(pair):
    _, reader, _ = pair
    snap = snapshot(reader, seconds=10)
    assert set(snap) == {
        "ts",
        "seconds",
        "step",
        "summary",
        "series",
        "consumers",
        "blocked_consumers",
        "routes",
    }
    assert len(snap["series"]) == 10
    assert snap["summary"]["requests"] == 0
    assert snap["consumers"] == [] and snap["routes"] == []


def test_the_summary_is_the_sum_of_the_series(pair):
    rec, reader, clock = pair
    for i in range(8):
        clock.set(T0 + i)
        rec.record("api", "ip:1", allowed=i % 4 != 0, tokens=2)
    clock.set(T0 + 9)
    snap = snapshot(reader, seconds=10)
    assert sum(p["allowed"] for p in snap["series"]) == snap["summary"]["allowed"] == 6
    assert snap["summary"]["blocked"] == 2
    assert snap["summary"]["tokens"] == 12


def test_step_makes_fewer_wider_points(pair):
    rec, reader, clock = pair
    rec.record("api", "ip:1", allowed=True, tokens=1)
    snap = snapshot(reader, seconds=60, step=10)
    assert len(snap["series"]) == 6
    assert snap["summary"]["allowed"] == 1  # same totals, coarser chart


def test_consumers_and_routes_are_listed(pair):
    rec, reader, _ = pair
    rec.record("chat", "alice", allowed=True, tokens=500)
    rec.record("chat", "bob", allowed=False)
    rec.record("login", "ip:1", allowed=True, tokens=1)
    snap = snapshot(reader, n=2)
    assert snap["consumers"][0]["key"] == "chat:alice"
    assert snap["blocked_consumers"][0]["key"] == "chat:bob"
    assert [r["scope"] for r in snap["routes"]] == ["chat", "login"]


def test_n_limits_every_list(pair):
    rec, reader, _ = pair
    for i in range(5):
        rec.record(f"route{i}", f"u{i}", allowed=True, tokens=i + 1)
    snap = snapshot(reader, n=2)
    assert len(snap["consumers"]) == len(snap["routes"]) == 2


def test_the_snapshot_is_valid_json(pair):
    rec, reader, _ = pair
    rec.record("api", "ip:1", allowed=True, tokens=0.5)
    json.dumps(snapshot(reader), allow_nan=False)  # no NaN or infinity anywhere


def test_bad_windows_raise_value_error(pair):
    _, reader, _ = pair
    with pytest.raises(ValueError):
        snapshot(reader, seconds=0)


def test_rankings_match_top_consumers(pair):
    rec, reader, _ = pair
    rec.record("api", "a", allowed=True, tokens=5)
    rec.record("api", "b", allowed=False)
    by_tokens, by_blocked = reader.rankings(n=5, minutes=2)
    assert by_tokens == reader.top_consumers(n=5, minutes=2, by="tokens")
    assert by_blocked == reader.top_consumers(n=5, minutes=2, by="blocked")
