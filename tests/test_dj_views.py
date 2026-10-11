import uuid

import pytest

pytest.importorskip("django")
pytest.importorskip("rest_framework")


def tg_config(url, **overrides):
    cfg = {
        "REDIS_URL": url,
        "DEFAULT_RULE": {"capacity": 3, "refill_rate": 0.0001},
        "FAIL_MODE": "open",
        "KEY_PREFIX": f"tgtest-{uuid.uuid4().hex[:8]}",
        "REDIS_TIMEOUT": 0.25,
        "TRUSTED_PROXIES": [],
        "EXEMPT": [r"^/health/"],
        "RULES": [
            {
                "name": "login",
                "match": r"^/login/",
                "capacity": 2,
                "refill_rate": 0.0001,
                "key": "ip",
                "fail_mode": "closed",
            }
        ],
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture
def tg(settings, redis_client, redis_url):
    """Fresh, isolated bucket namespace per test."""
    settings.TOKENGUARD = tg_config(redis_url)
    yield settings.TOKENGUARD
    prefix = settings.TOKENGUARD["KEY_PREFIX"]
    for k in redis_client.scan_iter(f"{prefix}:*"):
        redis_client.delete(k)


@pytest.fixture
def dead_redis(settings):
    """Points at a closed port. Needs no running Redis."""
    settings.TOKENGUARD = tg_config(
        "redis://localhost:1/0", REDIS_TIMEOUT=0.2, KEY_PREFIX="dead"
    )
    return settings


# ---- middleware: default rule ----
def test_default_rule_allows_then_blocks(client, tg):
    codes = [client.get("/api/ping/").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]


def test_exempt_path_is_never_limited(client, tg):
    assert all(client.get("/health/").status_code == 200 for _ in range(10))


def test_different_clients_have_separate_buckets(client, tg):
    for _ in range(3):
        client.get("/api/ping/", REMOTE_ADDR="1.1.1.1")
    assert client.get("/api/ping/", REMOTE_ADDR="1.1.1.1").status_code == 429
    assert client.get("/api/ping/", REMOTE_ADDR="2.2.2.2").status_code == 200


# ---- three routes, three different limits ----
def test_three_routes_have_three_different_limits(client, tg):
    ping = [client.get("/api/ping/").status_code for _ in range(5)]
    login = [client.get("/login/").status_code for _ in range(4)]
    report = [client.get("/api/report/").status_code for _ in range(6)]
    assert ping.count(200) == 3  # DEFAULT_RULE: capacity 3
    assert login.count(200) == 2  # RULES "login": capacity 2
    assert report.count(200) == 4  # decorator: capacity 20 / cost 5


# ---- decorator precedence ----
def test_decorated_view_is_charged_once_not_twice(client, tg, redis_client):
    client.get("/api/report/")
    remaining = client.get("/api/report/")["X-RateLimit-Remaining"]
    assert remaining == "10"  # 20 - 5 - 5; a double charge would show 0


def test_decorator_ignores_default_rule_capacity(client, tg):
    # DEFAULT_RULE says 3, but the decorated view allows 4 (decorator > default)
    assert [client.get("/api/report/").status_code for _ in range(4)] == [200] * 4


# ---- DRF class-based view wrapped in urls.py ----
def test_drf_view_is_limited(client, tg):
    codes = [client.get("/api/chat/").status_code for _ in range(12)]
    assert codes[:10] == [200] * 10  # capacity 10 (set in urls.py)
    assert codes[10:] == [429, 429]


# ---- 429 responses and headers ----
def test_headers_on_success(client, tg):
    r = client.get("/api/ping/")
    assert r.status_code == 200
    assert r["X-RateLimit-Limit"] == "3"
    assert r["X-RateLimit-Remaining"] == "2"
    assert int(r["X-RateLimit-Reset"]) > 0
    assert "Retry-After" not in r


def test_429_body_and_headers(client, tg):
    for _ in range(3):
        client.get("/api/ping/")
    r = client.get("/api/ping/")
    assert r.status_code == 429
    body = r.json()
    assert body["error"] == "rate_limited"
    assert body["retry_after"] > 0
    assert int(r["Retry-After"]) >= 1  # integer seconds, rounded up
    assert r["X-RateLimit-Remaining"] == "0"
    assert r["X-RateLimit-Limit"] == "3"


# ---- fail-open / fail-closed (Redis unreachable) ----
def test_fail_open_lets_request_through(client, dead_redis, caplog):
    r = client.get("/api/ping/")
    assert r.status_code == 200
    assert "X-RateLimit-Limit" not in r  # no decision was made
    assert "failing OPEN" in caplog.text


def test_fail_closed_returns_503(client, dead_redis):
    dead_redis.TOKENGUARD["FAIL_MODE"] = "closed"
    r = client.get("/api/ping/")
    assert r.status_code == 503
    assert r.json() == {"error": "rate_limiter_unavailable"}


def test_per_rule_fail_mode_overrides_global(client, dead_redis):
    # global is open, but the login rule says closed
    assert client.get("/api/ping/").status_code == 200
    assert client.get("/login/").status_code == 503


def test_exempt_path_works_even_if_redis_is_down(client, dead_redis):
    dead_redis.TOKENGUARD["FAIL_MODE"] = "closed"
    assert client.get("/health/").status_code == 200


def test_bad_fail_mode_is_a_config_error(client, dead_redis):
    from django.core.exceptions import ImproperlyConfigured

    dead_redis.TOKENGUARD["FAIL_MODE"] = "banana"
    with pytest.raises(ImproperlyConfigured):
        client.get("/api/ping/")


def test_cbv_method_decorator_limited_and_charged_once(client, tg):
    first = client.get("/api/summary/")
    assert first["X-RateLimit-Remaining"] == "9"  # charged once, not twice
    codes = [first.status_code] + [
        client.get("/api/summary/").status_code for _ in range(11)
    ]
    assert codes[:10] == [200] * 10  # capacity 10
    assert codes[10:] == [429, 429]
