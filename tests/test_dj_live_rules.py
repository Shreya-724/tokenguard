"""Live rule changes through Django: no redeploy, no restart."""

import uuid
from types import SimpleNamespace

import pytest

pytest.importorskip("django")
pytest.importorskip("rest_framework")

from tokenguard import FakeClock  # noqa: E402
from tokenguard.django.conf import get_rule_store  # noqa: E402
from tokenguard.rulestore import RuleStore  # noqa: E402

TTL = 5.0
VERSION = "X-TokenGuard-Rules-Version"


def config(url, prefix, **overrides):
    cfg = {
        "REDIS_URL": url,
        "KEY_PREFIX": prefix,
        "DEFAULT_RULE": {"capacity": 3, "refill_rate": 0.001},
        "EXEMPT": [r"^/health/"],
        "RULES": [
            {
                "name": "login",
                "match": r"^/login/",
                "capacity": 2,
                "refill_rate": 0.001,
                "key": "ip",
            }
        ],
        "LIVE_RULES": True,
        "LIVE_RULES_TTL": TTL,
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture
def live(settings, redis_client, redis_url):
    """Live rules on, with a fake clock for the server's cache."""
    prefix = f"tglive-{uuid.uuid4().hex[:8]}"
    settings.TOKENGUARD = config(redis_url, prefix)
    clock = FakeClock(1_000)
    store = get_rule_store()  # the one the server uses
    store.clock = clock.now
    yield SimpleNamespace(store=store, clock=clock, prefix=prefix, url=redis_url)
    for k in redis_client.scan_iter(f"{prefix}:*"):
        redis_client.delete(k)


def codes(client, path, count):
    return [client.get(path).status_code for _ in range(count)]


# ---- off unless asked for ----
def test_overrides_do_nothing_unless_live_rules_is_on(
    client, settings, redis_client, redis_url
):
    prefix = f"tglive-{uuid.uuid4().hex[:8]}"
    settings.TOKENGUARD = config(redis_url, prefix, LIVE_RULES=False)
    RuleStore(redis_client, f"{prefix}:").set_rule("default", capacity=50)
    r = client.get("/api/ping/")
    assert r["X-RateLimit-Limit"] == "3"
    assert VERSION not in r
    for k in redis_client.scan_iter(f"{prefix}:*"):
        redis_client.delete(k)


# ---- changing a limit ----
def test_a_new_limit_applies_to_the_very_next_request(client, live):
    first = client.get("/api/ping/")
    assert first["X-RateLimit-Limit"] == "3" and first["X-RateLimit-Remaining"] == "2"
    live.store.set_rule("default", capacity=1)
    second = client.get("/api/ping/")  # a bucket of 1: the 2 left are cut to 1
    assert second.status_code == 200
    assert second["X-RateLimit-Limit"] == "1" and second["X-RateLimit-Remaining"] == "0"
    assert client.get("/api/ping/").status_code == 429


def test_headers_show_the_limit_and_the_rules_version(client, live):
    before = client.get("/api/ping/")
    assert (before["X-RateLimit-Limit"], before[VERSION]) == ("3", "0")
    live.store.set_rule("default", capacity=10)
    after = client.get("/api/ping/")
    assert (after["X-RateLimit-Limit"], after[VERSION]) == ("10", "1")


def test_a_blocked_response_carries_the_version_too(client, live):
    codes(client, "/api/ping/", 3)
    blocked = client.get("/api/ping/")
    assert blocked.status_code == 429 and blocked[VERSION] == "0"


def test_a_rule_from_settings_can_be_changed_live(client, live):
    assert codes(client, "/login/", 3) == [200, 200, 429]
    live.store.set_rule("login", algorithm="fixed_window")  # a fresh counter
    assert codes(client, "/login/", 3) == [200, 200, 429]
    assert client.get("/login/")["X-RateLimit-Limit"] == "2"


def test_a_decorated_view_can_be_changed_live(client, live):
    # /api/fixed/ is decorated: capacity 5, a fixed window
    live.store.set_rule("demo_site.views.fixed", capacity=2)
    assert codes(client, "/api/fixed/", 4) == [200, 200, 429, 429]


def test_deleting_an_override_returns_to_the_configured_rule(client, live):
    live.store.set_rule("default", capacity=10)
    assert client.get("/api/ping/")["X-RateLimit-Limit"] == "10"
    live.store.delete_rule("default")
    back = client.get("/api/ping/")
    assert (back["X-RateLimit-Limit"], back[VERSION]) == ("3", "2")


# ---- spreading to other servers ----
def test_a_change_made_elsewhere_arrives_after_the_cache_expires(
    client, live, redis_client
):
    admin = RuleStore(redis_client, f"{live.prefix}:")  # another process
    assert client.get("/api/ping/")["X-RateLimit-Limit"] == "3"  # server caches
    admin.set_rule("default", capacity=10)

    live.clock.advance(TTL - 0.5)
    assert client.get("/api/ping/")["X-RateLimit-Limit"] == "3"  # not yet
    live.clock.advance(0.5)
    now = client.get("/api/ping/")
    assert (now["X-RateLimit-Limit"], now[VERSION]) == ("10", "1")


# ---- safety ----
def test_an_override_that_cannot_apply_is_ignored_not_fatal(client, live):
    # a budget needs the token bucket, so a fixed window cannot be forced on it
    live.store.set_rule("demo_site.views.budgeted", algorithm="fixed_window")
    r = client.post(
        "/api/budgeted/",
        data='{"prompt": "hi", "max_tokens": 5}',
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r["X-RateLimit-Limit"] == "10000"


def test_the_exempt_path_stays_exempt(client, live):
    live.store.set_rule("default", capacity=1)
    assert all(client.get("/health/").status_code == 200 for _ in range(5))
