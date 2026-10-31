"""Security review (Week 7, Day 7): what a hostile client can and cannot do."""

import uuid

import pytest
import redis

pytest.importorskip("django")
pytest.importorskip("rest_framework")

from django.core.exceptions import ImproperlyConfigured  # noqa: E402
from django.http import JsonResponse  # noqa: E402

from tokenguard.django import rate_limit  # noqa: E402
from tokenguard.django.conf import get_setting  # noqa: E402


def config(url, **overrides):
    cfg = {
        "REDIS_URL": url,
        "DEFAULT_RULE": {"capacity": 3, "refill_rate": 0.0001},
        "FAIL_MODE": "open",
        "KEY_PREFIX": f"tgsec-{uuid.uuid4().hex[:8]}",
        "REDIS_TIMEOUT": 0.25,
        "TRUSTED_PROXIES": [],
        "EXEMPT": [r"^/health/"],
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture
def tg(settings, redis_client, redis_url):
    settings.TOKENGUARD = config(redis_url)
    yield settings.TOKENGUARD
    for key in redis_client.scan_iter(f"{settings.TOKENGUARD['KEY_PREFIX']}:*"):
        redis_client.delete(key)


@pytest.fixture
def rf():
    from django.test import RequestFactory

    return RequestFactory()


def keys_of(redis_client, tg):
    return list(redis_client.scan_iter(f"{tg['KEY_PREFIX']}:*"))


# ---- X-Forwarded-For spoofing ----
def test_a_fake_forwarded_for_header_does_not_buy_a_new_bucket(client, tg):
    codes = [
        client.get(
            "/api/ping/", REMOTE_ADDR="9.9.9.9", HTTP_X_FORWARDED_FOR=f"10.1.1.{i}"
        ).status_code
        for i in range(6)
    ]
    assert codes == [200, 200, 200, 429, 429, 429]  # one client, whatever it claims


def test_behind_a_trusted_proxy_extra_left_entries_are_ignored(client, tg):
    tg["TRUSTED_PROXIES"] = ["10.0.0.0/8"]
    codes = [
        client.get(
            "/api/ping/",
            REMOTE_ADDR="10.0.0.1",  # our proxy
            HTTP_X_FORWARDED_FOR=f"6.6.6.{i}, 7.7.7.7",  # 7.7.7.7 is what it saw
        ).status_code
        for i in range(5)
    ]
    assert codes == [200, 200, 200, 429, 429]


# ---- unbounded key growth ----
def test_an_overlong_identity_cannot_make_a_huge_redis_key(rf, redis_client, tg):
    @rate_limit(capacity=2, refill_rate=0.0001, key=lambda r: r.META["HTTP_X_TOKEN"])
    def view(request):
        return JsonResponse({"ok": True})

    huge = "A" * 100_000
    codes = [view(rf.get("/x/", HTTP_X_TOKEN=huge)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]  # still one bucket, still limited
    longest = max(len(k) for k in keys_of(redis_client, tg))
    assert longest < len(tg["KEY_PREFIX"]) + 200


def test_the_key_length_limit_is_configurable_and_validated(tg):
    assert get_setting("MAX_KEY_LENGTH") == 128
    tg["MAX_KEY_LENGTH"] = 40
    assert get_setting("MAX_KEY_LENGTH") == 40
    for bad in (5, "40", None, True, 15):
        tg["MAX_KEY_LENGTH"] = bad
        with pytest.raises(ImproperlyConfigured):
            get_setting("MAX_KEY_LENGTH")


def test_a_flood_of_random_callers_leaves_only_expiring_keys(rf, redis_client, tg):
    @rate_limit(capacity=5, refill_rate=1, key="api_key")
    def view(request):
        return JsonResponse({"ok": True})

    for _ in range(40):
        view(rf.get("/x/", HTTP_X_API_KEY=uuid.uuid4().hex))
    found = keys_of(redis_client, tg)
    assert len(found) == 40  # each random key gets a bucket (documented)...
    assert all(0 < redis_client.ttl(k) <= 10 for k in found)  # ...that expires


# ---- Redis failures ----
@pytest.fixture
def redis_is_out_of_memory():
    from tokenguard.redis_bucket import RedisTokenBucket

    def refuse(self, cost, spend):
        raise redis.ResponseError(
            "OOM command not allowed when used memory > maxmemory"
        )

    original = RedisTokenBucket._run
    RedisTokenBucket._run = refuse
    yield
    RedisTokenBucket._run = original


def test_out_of_memory_fails_open_when_configured(client, tg, redis_is_out_of_memory):
    assert client.get("/api/ping/").status_code == 200


def test_out_of_memory_fails_closed_when_configured(client, tg, redis_is_out_of_memory):
    tg["FAIL_MODE"] = "closed"
    assert client.get("/api/ping/").status_code == 503


# ---- made-up API keys ----
def test_made_up_api_keys_are_limited_by_ip_when_you_check_them(rf, redis_client, tg):
    from tokenguard.django.keys import api_key_if

    known = {"real-key"}

    @rate_limit(capacity=2, refill_rate=0.0001, key=api_key_if(known.__contains__))
    def view(request):
        return JsonResponse({"ok": True})

    def call(raw):
        return view(
            rf.get("/x/", HTTP_X_API_KEY=raw, REMOTE_ADDR="8.8.8.8")
        ).status_code

    fakes = [call(uuid.uuid4().hex) for _ in range(4)]
    assert fakes == [200, 200, 429, 429]  # rotating keys bought nothing
    assert call("real-key") == 200  # a real key has its own bucket
    assert len(keys_of(redis_client, tg)) == 2  # the IP's and the real key's
