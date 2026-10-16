"""Choosing the algorithm: globally, per route, and per view."""

import time
import uuid

import pytest

pytest.importorskip("django")
pytest.importorskip("rest_framework")

from django.core.exceptions import ImproperlyConfigured  # noqa: E402
from django.http import HttpResponse  # noqa: E402

from tokenguard.budget import Budget  # noqa: E402
from tokenguard.django import rate_limit  # noqa: E402


@pytest.fixture
def ns(settings, redis_client, redis_url):
    """A fresh Redis namespace. Tests add the settings they care about."""
    prefix = f"tgalgo-{uuid.uuid4().hex[:8]}"
    settings.TOKENGUARD = {
        "REDIS_URL": redis_url,
        "KEY_PREFIX": prefix,
        "DEFAULT_RULE": {"capacity": 3, "refill_rate": 0.001},  # window: 3,000s
        "EXEMPT": [r"^/health/"],
    }
    yield prefix
    for k in redis_client.scan_iter(f"{prefix}:*"):
        redis_client.delete(k)


def codes(client, path, count):
    return [client.get(path).status_code for _ in range(count)]


# ---- per view: @rate_limit(algorithm=...) ----
def test_a_view_can_ask_for_a_fixed_window(client, ns):
    # /api/fixed/: capacity 5, refill_rate 0.001, algorithm="fixed_window"
    assert codes(client, "/api/fixed/", 7) == [200] * 5 + [429, 429]


def test_fixed_window_headers_describe_the_window(client, ns):
    first = client.get("/api/fixed/")
    assert first["X-RateLimit-Limit"] == "5"
    assert first["X-RateLimit-Remaining"] == "4"
    # Reset is the end of the window (at most 5,000s away), not "when full again"
    assert 0 < int(first["X-RateLimit-Reset"]) - time.time() <= 5_001
    for _ in range(4):
        client.get("/api/fixed/")
    blocked = client.get("/api/fixed/")
    assert blocked.status_code == 429
    assert blocked["X-RateLimit-Remaining"] == "0"
    assert 1 <= int(blocked["Retry-After"]) <= 5_000
    assert blocked.json()["error"] == "rate_limited"


def test_fixed_window_state_lives_under_its_own_key(client, redis_client, ns):
    client.get("/api/fixed/")
    assert list(redis_client.scan_iter(f"{ns}:fw:*"))


# ---- globally: the ALGORITHM setting ----
def test_the_default_algorithm_is_the_token_bucket(client, redis_client, ns):
    assert codes(client, "/api/ping/", 5) == [200, 200, 200, 429, 429]
    assert not list(redis_client.scan_iter(f"{ns}:fw:*"))
    assert list(redis_client.scan_iter(f"{ns}:default:*"))


def test_the_global_setting_switches_every_default_rule(
    client, redis_client, ns, settings
):
    settings.TOKENGUARD["ALGORITHM"] = "fixed_window"
    assert codes(client, "/api/ping/", 5) == [200, 200, 200, 429, 429]
    assert list(redis_client.scan_iter(f"{ns}:fw:default:*"))


def test_a_sliding_window_can_be_the_global_algorithm(
    client, redis_client, ns, settings
):
    settings.TOKENGUARD["ALGORITHM"] = "sliding_window"
    assert codes(client, "/api/ping/", 5) == [200, 200, 200, 429, 429]
    assert list(redis_client.scan_iter(f"{ns}:sw:default:*"))
    blocked = client.get("/api/ping/")
    assert 1 <= int(blocked["Retry-After"]) <= 3_000  # exact: when an entry expires


def test_a_view_can_override_the_global_algorithm(rf, redis_client, ns, settings):
    settings.TOKENGUARD["ALGORITHM"] = "fixed_window"

    @rate_limit(capacity=2, refill_rate=0.001, key="ip", algorithm="token_bucket")
    def view(request):
        return HttpResponse("ok")

    assert [view(rf.get("/x")).status_code for _ in range(3)] == [200, 200, 429]
    assert not list(redis_client.scan_iter(f"{ns}:fw:*"))


# ---- per route: RULES entries ----
def test_a_route_rule_can_pick_its_own_algorithm(client, redis_client, ns, settings):
    settings.TOKENGUARD["RULES"] = [
        {
            "name": "login",
            "match": r"^/login/",
            "capacity": 2,
            "refill_rate": 0.001,
            "key": "ip",
            "algorithm": "fixed_window",
        }
    ]
    assert codes(client, "/login/", 4) == [200, 200, 429, 429]
    assert list(redis_client.scan_iter(f"{ns}:fw:login:*"))
    # other routes keep the global default, the token bucket
    assert codes(client, "/api/ping/", 4) == [200, 200, 200, 429]


# ---- mistakes are loud ----
def test_an_unknown_global_algorithm_is_a_configuration_error(client, ns, settings):
    settings.TOKENGUARD["ALGORITHM"] = "leaky_bucket"
    with pytest.raises(ImproperlyConfigured):
        client.get("/api/ping/")


def test_an_unknown_algorithm_on_a_view_fails_at_startup():
    with pytest.raises(ValueError, match="unknown algorithm"):
        rate_limit(capacity=1, refill_rate=1, algorithm="leaky_bucket")(lambda r: r)


def test_budgets_need_the_token_bucket():
    with pytest.raises(ValueError, match="budget"):
        rate_limit(
            capacity=1,
            refill_rate=1,
            algorithm="fixed_window",
            budget=Budget(daily_tokens=10),
        )(lambda r: r)


# ---- Redis down ----
def test_fixed_window_fails_open_or_closed_like_the_token_bucket(client, settings):
    settings.TOKENGUARD = {
        "REDIS_URL": "redis://localhost:1/0",
        "REDIS_TIMEOUT": 0.2,
        "KEY_PREFIX": "dead",
        "ALGORITHM": "fixed_window",
        "DEFAULT_RULE": {"capacity": 3, "refill_rate": 1},
    }
    assert client.get("/api/ping/").status_code == 200  # fail open (the default)
    settings.TOKENGUARD["FAIL_MODE"] = "closed"
    assert client.get("/api/ping/").status_code == 503
