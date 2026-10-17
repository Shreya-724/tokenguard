"""Live rule changes: the store, its cache, and how fast a change spreads."""

import json
import threading
import uuid

import pytest
import redis

from tokenguard import FakeClock
from tokenguard.errors import RedisUnavailableError
from tokenguard.rulestore import RuleOverride, RuleStore, validate_override

TTL = 5.0


@pytest.fixture
def prefix(redis_client):
    p = f"test:{uuid.uuid4().hex}:"
    yield p
    for k in redis_client.scan_iter(f"{p}*"):
        redis_client.delete(k)


class CountingClient:
    """Wraps a Redis client: counts reads, and can pretend Redis is down."""

    def __init__(self, client):
        self._c = client
        self.reads = 0
        self.down = False

    def hgetall(self, key):
        self.reads += 1
        if self.down:
            raise redis.ConnectionError("pretend Redis is down")
        return self._c.hgetall(key)

    def __getattr__(self, name):
        return getattr(self._c, name)


def new_store(client, prefix):
    clock = FakeClock(1_000)
    return RuleStore(client, prefix, ttl=TTL, clock=clock.now), clock


# ---- writing and reading ----
def test_a_fresh_store_has_no_overrides_and_version_zero(redis_client, prefix):
    store, _ = new_store(redis_client, prefix)
    snap = store.snapshot()
    assert snap.version == 0 and snap.overrides == {} and snap.loaded


def test_set_rule_returns_a_rising_version(redis_client, prefix):
    store, _ = new_store(redis_client, prefix)
    assert store.set_rule("login", capacity=20) == 1
    assert store.set_rule("login", capacity=30) == 2
    assert store.set_rule("default", refill_rate=5) == 3
    assert store.version == 3


def test_an_override_holds_only_the_fields_you_set(redis_client, prefix):
    store, _ = new_store(redis_client, prefix)
    store.set_rule("login", capacity=20, algorithm="fixed_window")
    assert store.get("login") == RuleOverride(20.0, None, "fixed_window")


def test_setting_a_rule_replaces_it(redis_client, prefix):
    store, _ = new_store(redis_client, prefix)
    store.set_rule("login", capacity=20, refill_rate=2)
    store.set_rule("login", capacity=50)
    assert store.get("login") == RuleOverride(50.0, None, None)


def test_delete_removes_the_override_and_bumps_the_version(redis_client, prefix):
    store, _ = new_store(redis_client, prefix)
    store.set_rule("login", capacity=20)
    assert store.delete_rule("login") == 2
    assert store.get("login") is None
    assert store.version == 2


def test_deleting_a_missing_rule_changes_nothing(redis_client, prefix):
    store, _ = new_store(redis_client, prefix)
    assert store.delete_rule("ghost") is None
    assert store.version == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {},  # nothing to override
        {"capacity": 0},
        {"capacity": -5},
        {"refill_rate": 0},
        {"capacity": float("nan")},
        {"capacity": float("inf")},
        {"capacity": "lots"},
        {"capacity": True},
        {"algorithm": "leaky_bucket"},
    ],
)
def test_bad_overrides_are_rejected_and_change_nothing(redis_client, prefix, kwargs):
    store, _ = new_store(redis_client, prefix)
    with pytest.raises(ValueError):
        store.set_rule("login", **kwargs)
    assert store.version == 0


@pytest.mark.parametrize("name", ["", "__version__", None, 5])
def test_bad_names_are_rejected(redis_client, prefix, name):
    store, _ = new_store(redis_client, prefix)
    with pytest.raises(ValueError):
        store.set_rule(name, capacity=5)


def test_validate_override_converts_numbers_to_floats():
    assert validate_override(capacity=5, refill_rate=2) == RuleOverride(5.0, 2.0, None)


def test_concurrent_changes_all_get_their_own_version(redis_client, prefix):
    store, _ = new_store(redis_client, prefix)
    versions = []

    def change(i):
        versions.append(store.set_rule(f"rule-{i}", capacity=i + 1))

    threads = [threading.Thread(target=change, args=(i,)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(versions) == list(range(1, 21))  # no version used twice
    assert store.refresh().version == 20
    assert len(store.snapshot().overrides) == 20


# ---- the cache, and the propagation delay ----
def test_requests_are_served_from_the_cache_between_refreshes(redis_client, prefix):
    counting = CountingClient(redis_client)
    store, clock = new_store(counting, prefix)
    for _ in range(100):
        store.get("login")
    assert counting.reads == 1  # one Redis read for a hundred requests
    clock.advance(TTL - 0.01)
    store.get("login")
    assert counting.reads == 1
    clock.advance(0.02)  # the cache is now older than the ttl
    store.get("login")
    assert counting.reads == 2


def test_a_change_reaches_another_process_within_the_ttl(redis_client, prefix):
    admin, _ = new_store(redis_client, prefix)  # where the change is made
    server, clock = new_store(redis_client, prefix)  # another process, cached
    assert server.get("login") is None  # it has cached "no override" at t=1000
    admin.set_rule("login", capacity=20)

    clock.advance(TTL - 0.1)  # still inside its cache window
    assert server.get("login") is None  # the old rules, up to ttl seconds late
    clock.advance(0.1)  # the cache expires
    assert server.get("login") == RuleOverride(20.0, None, None)
    assert server.version == 1


def test_the_process_that_makes_a_change_sees_it_immediately(redis_client, prefix):
    store, _ = new_store(redis_client, prefix)
    assert store.get("login") is None  # cached
    store.set_rule("login", capacity=20)
    assert store.get("login") is not None  # no waiting for its own change
    store.delete_rule("login")
    assert store.get("login") is None


def test_refresh_and_invalidate_skip_the_wait(redis_client, prefix):
    admin, _ = new_store(redis_client, prefix)
    server, _ = new_store(redis_client, prefix)
    server.get("login")
    admin.set_rule("login", capacity=20)
    assert server.get("login") is None
    assert server.refresh().overrides["login"].capacity == 20
    admin.set_rule("login", capacity=30)
    server.invalidate()
    assert server.get("login").capacity == 30


def test_a_zero_ttl_checks_redis_every_time(redis_client, prefix):
    counting = CountingClient(redis_client)
    store = RuleStore(counting, prefix, ttl=0, clock=FakeClock(1).now)
    store.get("a")
    store.get("a")
    assert counting.reads == 2


def test_versions_never_go_backwards_for_a_reader(redis_client, prefix):
    admin, _ = new_store(redis_client, prefix)
    server, clock = new_store(redis_client, prefix)
    seen = []
    for i in range(6):
        admin.set_rule("login", capacity=i + 1)
        clock.advance(TTL)
        seen.append(server.version)
    assert seen == sorted(seen) and seen[-1] == 6


# ---- when Redis is not there ----
def test_the_last_known_rules_survive_a_redis_outage(redis_client, prefix):
    counting = CountingClient(redis_client)
    store, clock = new_store(counting, prefix)
    store.set_rule("login", capacity=20)
    assert store.get("login").capacity == 20
    counting.down = True
    clock.advance(TTL)
    assert store.get("login").capacity == 20  # stale, but never an error
    assert store.snapshot().loaded


def test_a_failed_refresh_is_not_retried_on_every_request(redis_client, prefix):
    counting = CountingClient(redis_client)
    store, clock = new_store(counting, prefix)
    store.get("login")
    counting.down = True
    clock.advance(TTL)
    reads = counting.reads
    for _ in range(50):
        store.get("login")
    assert counting.reads == reads + 1  # one attempt, then it waits another ttl


def test_it_recovers_when_redis_comes_back(redis_client, prefix):
    counting = CountingClient(redis_client)
    admin, _ = new_store(redis_client, prefix)
    store, clock = new_store(counting, prefix)
    store.get("login")
    counting.down = True
    admin.set_rule("login", capacity=20)
    clock.advance(TTL)
    assert store.get("login") is None  # outage: still the old rules
    counting.down = False
    clock.advance(TTL)
    assert store.get("login").capacity == 20


def test_with_redis_down_from_the_start_there_are_no_overrides(redis_client, prefix):
    counting = CountingClient(redis_client)
    counting.down = True
    store, _ = new_store(counting, prefix)
    snap = store.get("login"), store.snapshot()
    assert snap[0] is None and not snap[1].loaded


def test_writing_while_redis_is_down_is_an_error(prefix):
    dead = redis.Redis.from_url("redis://localhost:1/0", socket_connect_timeout=0.2)
    store = RuleStore(dead, prefix)
    with pytest.raises(RedisUnavailableError):
        store.set_rule("login", capacity=5)


# ---- damaged data ----
def test_a_damaged_or_invalid_stored_rule_is_ignored(redis_client, prefix):
    store, _ = new_store(redis_client, prefix)
    store.set_rule("good", capacity=7)
    key = f"{prefix}{{rules}}"
    redis_client.hset(key, "broken", "{not json")
    redis_client.hset(key, "negative", json.dumps({"capacity": -3}))
    redis_client.hset(key, "wrong-type", json.dumps([1, 2]))
    redis_client.hset(key, "bad-algo", json.dumps({"algorithm": "nope"}))
    assert set(store.refresh().overrides) == {"good"}
