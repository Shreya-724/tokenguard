"""Metrics through Django: every decision is recorded, off unless asked for."""

import uuid

import pytest

pytest.importorskip("django")
pytest.importorskip("rest_framework")

from tokenguard.django.conf import get_metrics_reader  # noqa: E402
from tokenguard.django.engine import Rule, enforce  # noqa: E402


def config(url, prefix, **extra):
    cfg = {
        "REDIS_URL": url,
        "KEY_PREFIX": prefix,
        "DEFAULT_RULE": {"capacity": 3, "refill_rate": 0.001},
        "EXEMPT": [r"^/health/"],
        "METRICS": True,
    }
    cfg.update(extra)
    return cfg


@pytest.fixture
def prefix(redis_client):
    p = f"tgm-{uuid.uuid4().hex[:8]}"
    yield p
    for k in redis_client.scan_iter(f"{p}:*"):
        redis_client.delete(k)


@pytest.fixture
def on(settings, redis_url, prefix):
    settings.TOKENGUARD = config(redis_url, prefix)
    return get_metrics_reader()


def test_every_decision_is_recorded(client, on):
    codes = [client.get("/api/ping/").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 429, 429]
    s = on.summary(60)
    assert (s.allowed, s.blocked) == (3, 2)
    assert s.blocked_ratio == pytest.approx(0.4)


def test_exempt_paths_are_not_recorded(client, on):
    for _ in range(4):
        client.get("/health/")
    assert on.summary(60).requests == 0


def test_the_top_consumer_is_the_caller(client, on):
    for _ in range(4):
        client.get("/api/ping/")
    (top,) = on.top_consumers()
    assert top.scope == "default" and top.identity.startswith("ip:")
    assert (top.tokens, top.blocked) == (3, 1)
    assert on.routes()[0].scope == "default"


def test_the_decorator_scope_shows_up_per_route(client, on):
    for _ in range(7):
        client.get("/api/fixed/")  # capacity 5
    route = next(r for r in on.routes() if "fixed" in r.scope)
    assert (route.allowed, route.blocked) == (5, 2)


def test_metrics_are_off_by_default(client, settings, redis_url, prefix, redis_client):
    settings.TOKENGUARD = config(redis_url, prefix, METRICS=False)
    client.get("/api/ping/")
    assert [k for k in redis_client.scan_iter(f"{prefix}:metrics*")] == []


def test_an_oversized_request_counts_as_blocked(settings, redis_url, prefix, rf):
    settings.TOKENGUARD = config(redis_url, prefix)
    rule = Rule(10, 1, lambda r: "u1", scope="chat", cost=100)
    assert enforce(rf.get("/"), rule).rejection.status_code == 413
    s = get_metrics_reader().summary(60)
    assert (s.allowed, s.blocked, s.tokens) == (0, 1, 0)


def test_reconciling_corrects_the_token_count(settings, redis_url, prefix, rf):
    settings.TOKENGUARD = config(redis_url, prefix)
    rule = Rule(1000, 1, lambda r: "u1", scope="chat", cost=100)
    outcome = enforce(rf.get("/"), rule)
    reader = get_metrics_reader()
    assert reader.summary(60).tokens == 100  # the estimate
    outcome.charge.reconcile(40)  # really used 40
    assert reader.summary(60).tokens == 40
    assert reader.top_consumers()[0].tokens == 40


def test_a_refund_takes_the_request_off_the_top_list(settings, redis_url, prefix, rf):
    settings.TOKENGUARD = config(redis_url, prefix)
    rule = Rule(1000, 1, lambda r: "u1", scope="chat", cost=100)
    outcome = enforce(rf.get("/"), rule)
    outcome.charge.refund()
    reader = get_metrics_reader()
    assert reader.top_consumers() == []
    assert reader.summary(60).allowed == 1  # it was still a request


def test_a_second_reconcile_does_not_record_twice(settings, redis_url, prefix, rf):
    settings.TOKENGUARD = config(redis_url, prefix)
    rule = Rule(1000, 1, lambda r: "u1", scope="chat", cost=100)
    outcome = enforce(rf.get("/"), rule)
    outcome.charge.reconcile(40)
    outcome.charge.reconcile(10)
    assert get_metrics_reader().summary(60).tokens == 40


def test_a_broken_metrics_config_never_breaks_requests(
    client, settings, redis_url, prefix
):
    settings.TOKENGUARD = config(redis_url, prefix, METRICS_RETENTION=5)  # too small
    assert client.get("/api/ping/").status_code == 200


def test_metrics_work_with_budgets(settings, redis_url, prefix, rf):
    from tokenguard.budget import Budget

    settings.TOKENGUARD = config(redis_url, prefix)
    rule = Rule(1000, 1, lambda r: "u1", scope="chat", cost=50, budget=Budget(100, 0))
    for _ in range(3):
        enforce(rf.get("/"), rule)
    s = get_metrics_reader().summary(60)
    assert (s.allowed, s.blocked, s.tokens) == (2, 1, 100)
