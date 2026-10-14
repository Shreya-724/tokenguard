"""Reconciliation edge cases: overspend, zero usage, and failed requests.

The first group goes through the mock chat endpoint (burst bucket 5,000 plus a
daily/monthly budget). The second group uses small decorated views.
"""

import json
import uuid

import pytest

pytest.importorskip("django")
pytest.importorskip("rest_framework")

from django.http import HttpResponse  # noqa: E402

from tokenguard.budget import Cost  # noqa: E402
from tokenguard.django import rate_limit  # noqa: E402

CHAT = "/api/llm/chat/"
CAPACITY = 5_000


@pytest.fixture
def ns(settings, redis_client, redis_url):
    """A fresh Redis namespace per test."""
    prefix = f"tgedge-{uuid.uuid4().hex[:8]}"
    settings.TOKENGUARD = {"REDIS_URL": redis_url, "KEY_PREFIX": prefix}
    yield prefix
    for k in redis_client.scan_iter(f"{prefix}:*"):
        redis_client.delete(k)


def chat(client, prompt="x" * 200, **body):
    """One chat request. 200 characters is 50 tokens."""
    api_key = body.pop("api_key", "edge-key")
    body.setdefault("model", "small")
    body["messages"] = [{"role": "user", "content": prompt}]
    return client.post(
        CHAT,
        data=json.dumps(body),
        content_type="application/json",
        HTTP_X_API_KEY=api_key,
    )


def remaining(response):
    return int(response["X-RateLimit-Remaining"])


def spent(redis_client, prefix, period="day"):
    """(tokens, dollars) recorded for the one owner in this namespace."""
    keys = list(redis_client.scan_iter(f"{prefix}:*:{period}:*"))
    assert len(keys) == 1
    data = redis_client.hgetall(keys[0])
    return float(data["tokens"]), float(data["usd"])


# ---- actual > estimate ----
def test_actual_above_estimate_is_charged_the_difference(client, ns, redis_client):
    # estimate 50 + 100 = 150, but the model really produced 500 tokens: 550 total
    r = chat(client, max_tokens=100, mock_completion_tokens=500)
    assert r.status_code == 200
    assert abs(remaining(r) - (CAPACITY - 550)) <= 5
    tokens, _ = spent(redis_client, ns)
    assert tokens == pytest.approx(550)  # the budget books what was really used


def test_debt_is_capped_at_one_buckets_worth(client, ns):
    # really used 20,050 tokens: unbounded debt would be about -15,000
    r = chat(client, max_tokens=10, mock_completion_tokens=20_000)
    assert r.status_code == 200
    assert remaining(r) == 0
    blocked = chat(client, prompt="", max_tokens=1)  # costs 1 token
    assert blocked.status_code == 429
    assert blocked.json()["error"] == "rate_limited"
    # balance floors at -5,000, so about (5,000 + 1) / 50 per second, not ~300s
    assert 95 <= int(blocked["Retry-After"]) <= 106


# ---- zero usage ----
def test_zero_usage_refunds_everything(client, ns, redis_client):
    # estimate: 0 input + 100 output. The model reports 0 prompt and 0 completion.
    r = chat(client, prompt="", max_tokens=100, mock_completion_tokens=0)
    assert r.status_code == 200
    assert remaining(r) >= CAPACITY - 5
    assert spent(redis_client, ns, "day") == pytest.approx((0, 0))
    assert spent(redis_client, ns, "month") == pytest.approx((0, 0))


# ---- request errors ----
def test_server_error_refunds_everything(client, ns, redis_client):
    r = chat(client, max_tokens=1000, simulate_error=True)  # fake upstream: 502
    assert r.status_code == 502
    assert remaining(r) >= CAPACITY - 5  # not 3,950
    assert spent(redis_client, ns) == pytest.approx((0, 0))


def test_client_error_stays_charged(client, ns, redis_client):
    # an unknown model is the caller's mistake (400). Invalid requests are not free.
    r = chat(client, max_tokens=100, model="invented-model")
    assert r.status_code == 400
    assert abs(remaining(r) - (CAPACITY - 150)) <= 5
    tokens, _ = spent(redis_client, ns)
    assert tokens == pytest.approx(150)


# ---- decorated views, no HTTP ----
def edge_views(scope):
    """Three views sharing one bucket: capacity 1,000, cost 100 (the last: 1)."""
    rule = {"capacity": 1_000, "refill_rate": 1, "key": "ip", "scope": scope}

    @rate_limit(cost=Cost(100), **rule)
    def boom(request):
        raise RuntimeError("the view crashed")

    @rate_limit(cost=Cost(100), **rule)
    def settles_twice(request):
        request.tokenguard.reconcile(10)
        request.tokenguard.reconcile(900)  # ignored: only the first one counts
        return HttpResponse("ok")

    @rate_limit(cost=Cost(1), **rule)
    def look(request):
        return HttpResponse("ok")

    return boom, settles_twice, look


def test_a_view_that_raises_gets_a_full_refund(rf, ns):
    boom, _, look = edge_views("edge-boom")
    with pytest.raises(RuntimeError):
        boom(rf.get("/x"))
    # one token for looking: 999 if the crash was refunded, 899 if it was not
    assert remaining(look(rf.get("/x"))) >= 990


def test_only_the_first_settlement_counts(rf, ns):
    _, settles_twice, _ = edge_views("edge-twice")
    r = settles_twice(rf.get("/x"))
    assert 990 <= remaining(r) <= 991  # charged 100, settled to 10, not to 900
