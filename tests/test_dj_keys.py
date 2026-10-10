import types

import pytest

pytest.importorskip("django")

from tokenguard.django import keys  # noqa: E402


@pytest.fixture
def rf():
    from django.test import RequestFactory

    return RequestFactory()


def fake_user(pk=None):
    if pk is None:
        return types.SimpleNamespace(is_authenticated=False, pk=None)
    return types.SimpleNamespace(is_authenticated=True, pk=pk)


def test_ip_key(rf):
    assert keys.ip(rf.get("/", REMOTE_ADDR="1.2.3.4")) == "ip:1.2.3.4"


def test_user_key_for_authenticated_user(rf):
    req = rf.get("/")
    req.user = fake_user(42)
    assert keys.user(req) == "user:42"


def test_anonymous_user_falls_back_to_ip(rf):
    req = rf.get("/", REMOTE_ADDR="1.2.3.4")
    req.user = fake_user()
    assert keys.user(req) == "ip:1.2.3.4"
    assert keys.user(rf.get("/", REMOTE_ADDR="1.2.3.4")) == "ip:1.2.3.4"  # no .user


def test_api_key_is_hashed_never_stored_raw(rf):
    req = rf.get("/", HTTP_X_API_KEY="secret-key-123")
    result = keys.api_key(req)
    assert result.startswith("apikey:") and "secret" not in result
    assert result == keys.api_key(rf.get("/", HTTP_X_API_KEY="secret-key-123"))
    assert result != keys.api_key(rf.get("/", HTTP_X_API_KEY="other"))


def test_missing_api_key_falls_back_to_ip(rf):
    assert keys.api_key(rf.get("/", REMOTE_ADDR="9.9.9.9")) == "ip:9.9.9.9"


def test_endpoint_uses_route_not_raw_path(rf):
    assert keys.endpoint(rf.get("/api/ping/")) == "/api/ping/"


def test_unknown_paths_share_one_bucket(rf):
    assert keys.endpoint(rf.get("/nope/1")) == keys.endpoint(rf.get("/nope/2"))


def test_combined_key(rf):
    req = rf.get("/api/report/")
    req.user = fake_user(42)
    assert keys.user_endpoint(req) == "user:42:/api/report/"


def test_resolve_key_variants():
    assert keys.resolve_key(None) is keys.user
    assert keys.resolve_key("ip") is keys.ip
    f = lambda r: "x"  # noqa: E731
    assert keys.resolve_key(f) is f
    assert keys.resolve_key("tokenguard.django.keys.ip") is keys.ip


# ---- client IP and X-Forwarded-For (the classic spoofing hole) ----
def test_xff_ignored_without_trusted_proxies(rf, settings):
    settings.TOKENGUARD = {}
    req = rf.get("/", REMOTE_ADDR="5.5.5.5", HTTP_X_FORWARDED_FOR="6.6.6.6")
    assert keys.client_ip(req) == "5.5.5.5"


def test_xff_ignored_when_peer_is_not_a_trusted_proxy(rf, settings):
    settings.TOKENGUARD = {"TRUSTED_PROXIES": ["10.0.0.0/8"]}
    req = rf.get("/", REMOTE_ADDR="5.5.5.5", HTTP_X_FORWARDED_FOR="6.6.6.6")
    assert keys.client_ip(req) == "5.5.5.5"  # attacker connecting directly


def test_xff_trusted_behind_known_proxy(rf, settings):
    settings.TOKENGUARD = {"TRUSTED_PROXIES": ["10.0.0.0/8"]}
    req = rf.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="7.7.7.7")
    assert keys.client_ip(req) == "7.7.7.7"


def test_xff_spoofed_left_entries_are_ignored(rf, settings):
    settings.TOKENGUARD = {"TRUSTED_PROXIES": ["10.0.0.0/8"]}
    # client sent a fake "1.1.1.1"; our proxy appended the real address 7.7.7.7
    req = rf.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="1.1.1.1, 7.7.7.7")
    assert keys.client_ip(req) == "7.7.7.7"


def test_xff_skips_chained_trusted_proxies(rf, settings):
    settings.TOKENGUARD = {"TRUSTED_PROXIES": ["10.0.0.0/8"]}
    req = rf.get(
        "/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="7.7.7.7, 10.0.0.2"
    )
    assert keys.client_ip(req) == "7.7.7.7"


def test_garbage_in_xff_falls_back_to_peer(rf, settings):
    settings.TOKENGUARD = {"TRUSTED_PROXIES": ["10.0.0.0/8"]}
    req = rf.get("/", REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="not-an-ip")
    assert keys.client_ip(req) == "10.0.0.1"
