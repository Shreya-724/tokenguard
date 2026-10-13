import json
import uuid

import pytest

pytest.importorskip("django")

from tokenguard.budget import Usage  # noqa: E402
from tokenguard.django.llm import (  # noqa: E402
    llm_cost,
    llm_usage,
    model_key,
    user_model,
)

CAPACITY = 10_000  # the burst bucket of /api/complete/ in demo_site/views.py


@pytest.fixture
def rf():
    from django.test import RequestFactory

    return RequestFactory()


def json_request(rf, body, **extra):
    request = rf.post("/x", data=json.dumps(body), content_type="application/json")
    for name, value in extra.items():
        setattr(request, name, value)
    return request


# ---- cost, usage and key functions (no Redis needed) ----
def test_llm_cost_is_input_plus_output(rf):
    req = json_request(rf, {"model": "small", "prompt": "x" * 400, "max_tokens": 50})
    cost = llm_cost()(req)
    assert cost.tokens == 150
    assert cost.weight == 1


def test_llm_cost_includes_dollars_from_the_price_table(rf):
    req = json_request(rf, {"model": "small", "prompt": "x" * 400, "max_tokens": 50})
    # 100 input tokens at $0.15/M plus 50 output tokens at $0.60/M
    assert llm_cost()(req).dollars == pytest.approx(100 * 0.15e-6 + 50 * 0.60e-6)


def test_llm_cost_carries_the_models_weight(rf):
    req = json_request(rf, {"model": "large", "prompt": "x" * 400})
    cost = llm_cost()(req)
    assert cost.tokens == 100 + 512
    assert (cost.weight, cost.burst) == (5, 5 * (100 + 512))


def test_llm_cost_uses_model_default_output(rf):
    req = json_request(rf, {"model": "small", "prompt": "x" * 400})
    assert llm_cost()(req).tokens == 100 + 256


def test_llm_cost_understands_chat_messages(rf):
    body = {"messages": [{"role": "user", "content": "x" * 40}], "max_tokens": 0}
    assert llm_cost(prompt_field="messages")(json_request(rf, body)).tokens == 10


def test_llm_cost_bad_json_is_cheap_not_a_crash(rf):
    req = rf.post("/x", data="{not json", content_type="application/json")
    assert llm_cost()(req).tokens == 1


def test_llm_cost_ignores_nonsense_max_tokens(rf):
    req = json_request(rf, {"prompt": "x" * 400, "max_tokens": "lots"})
    assert llm_cost()(req).tokens == 100 + 256


def test_llm_cost_survives_a_weird_model_value(rf):
    req = json_request(rf, {"model": ["not", "a", "string"], "prompt": "hi"})
    assert llm_cost()(req).weight == 1  # falls back to the default model


def test_llm_usage_reads_total_or_parts():
    class R:
        def __init__(self, content):
            self.content = content

    class Req:
        body = b'{"model": "small"}'

    usage = llm_usage()
    assert usage(Req, R(b'{"usage": {"total_tokens": 90}}')) == Usage(90.0)
    parts = b'{"usage": {"prompt_tokens": 50, "completion_tokens": 40}}'
    got = usage(Req, R(parts))
    assert got.tokens == 90
    assert got.dollars == pytest.approx(50 * 0.15e-6 + 40 * 0.60e-6)
    assert usage(Req, R(b'{"error": "nope"}')) is None
    assert usage(Req, R(b"not json")) is None


def test_model_key_and_user_model_key(rf):
    large = json_request(rf, {"model": "large"}, REMOTE_ADDR="1.2.3.4")
    assert model_key()(large) == "model:large"
    assert user_model(large) == "ip:127.0.0.1:model:large"
    unknown = json_request(rf, {"model": "invented-123"})
    assert model_key()(unknown) == "model:small"  # unknown names share one bucket


# ---- end to end through the demo endpoints (needs Redis) ----
@pytest.fixture
def llm(settings, redis_client, redis_url):
    prefix = f"tgllm-{uuid.uuid4().hex[:8]}"
    settings.TOKENGUARD = {"REDIS_URL": redis_url, "KEY_PREFIX": prefix}
    yield prefix
    for k in redis_client.scan_iter(f"{prefix}:*"):
        redis_client.delete(k)


def post(client, ip="10.0.0.1", path="/api/complete/", **body):
    body.setdefault("model", "small")
    body.setdefault("prompt", "x" * 200)  # 50 tokens
    return client.post(
        path,
        data=json.dumps(body),
        content_type="application/json",
        REMOTE_ADDR=ip,
    )


def remaining(response):
    return int(response["X-RateLimit-Remaining"])


def test_small_and_huge_requests_drain_very_differently(client, llm):
    small = post(client, ip="10.0.0.1", max_tokens=0)  # 50 tokens
    big = post(client, ip="10.0.0.2", prompt="x" * 20_000, max_tokens=0)  # 5,000
    assert abs(remaining(small) - 9_950) <= 5
    assert abs(remaining(big) - 5_000) <= 5


def test_request_above_capacity_is_413_not_retry_later(client, llm):
    r = post(client, prompt="x" * 200_000, max_tokens=0)  # 50,000 > 10,000
    assert r.status_code == 413
    assert r.json()["error"] == "request_too_large"
    assert r.json()["cost"] == 50_000
    assert "Retry-After" not in r
    # and it cost nothing: the next small request sees an untouched bucket
    assert remaining(post(client, max_tokens=0)) >= 9_940


def test_unused_tokens_are_refunded(client, llm):
    # estimate: 50 input + 1,000 output = 1,050. The mock really uses 50 + 40.
    r = post(client, max_tokens=1000)
    assert abs(remaining(r) - 9_910) <= 5  # not 8,950


def test_upstream_error_refunds_everything(client, llm):
    r = post(client, max_tokens=1000, simulate_error=True)
    assert r.status_code == 502
    assert remaining(r) == 10_000


def test_overspend_creates_debt_and_blocks_the_next_request(client, llm):
    # estimate 150, but the model really produced 12,000 completion tokens
    first = post(client, max_tokens=100, mock_completion_tokens=12_000)
    assert first.status_code == 200
    assert remaining(first) == 0  # balance is about -2,050 (shown as 0)
    second = post(client, max_tokens=0)
    assert second.status_code == 429
    assert 40 <= int(second["Retry-After"]) <= 45  # ~(50 + 2,050) / 50 per sec


def test_view_can_reconcile_itself_via_request_tokenguard(client, llm):
    # /api/complete-manual/ calls request.tokenguard.reconcile(...) in the view
    r = post(client, ip="10.0.0.9", path="/api/complete-manual/", max_tokens=1000)
    assert abs(remaining(r) - 9_910) <= 5


# ---- Day 4: per-model weights and isolation ----
def test_the_large_model_counts_five_times(client, llm):
    prompt = "x" * 8_000  # 2,000 input tokens
    small = post(client, ip="10.0.1.1", prompt=prompt, max_tokens=0)
    large = post(client, ip="10.0.1.2", prompt=prompt, model="large", max_tokens=0)
    assert abs(remaining(small) - 8_000) <= 5  # 2,000 x 1
    assert remaining(large) == 0  # 2,000 x 5 = the whole 10,000 bucket


def test_heavy_large_model_use_does_not_block_the_small_model(client, llm):
    prompt = "x" * 8_000
    assert post(client, prompt=prompt, model="large", max_tokens=0).status_code == 200
    blocked = post(client, prompt=prompt, model="large", max_tokens=0)
    assert blocked.status_code == 429  # the large bucket is empty
    small = post(client, model="small", max_tokens=0)  # same user, same IP
    assert small.status_code == 200
    assert abs(remaining(small) - 9_950) <= 5  # the small bucket is untouched


# ---- Day 5: budgets, dollars, near-limit alerts ----
def day_hash(redis_client, prefix):
    keys = list(redis_client.scan_iter(f"{prefix}:*:day:*"))
    assert len(keys) == 1
    return redis_client.hgetall(keys[0])


def test_spend_is_tracked_in_tokens_and_dollars(client, llm, redis_client):
    # real usage: 50 prompt + 700 completion tokens on the small model
    r = post(client, path="/api/budgeted/", max_tokens=800, mock_completion_tokens=700)
    assert r.status_code == 200
    day = day_hash(redis_client, llm)
    assert float(day["tokens"]) == pytest.approx(750)
    assert float(day["usd"]) == pytest.approx(50 * 0.15e-6 + 700 * 0.60e-6)
    month = redis_client.hgetall(next(redis_client.scan_iter(f"{llm}:*:month:*")))
    assert float(month["tokens"]) == pytest.approx(750)


def test_exceeding_the_daily_cap_blocks_even_though_burst_has_tokens(client, llm):
    first = post(
        client, path="/api/budgeted/", max_tokens=800, mock_completion_tokens=700
    )
    assert first.status_code == 200  # really used 750 of the 1,000 daily tokens
    second = post(client, path="/api/budgeted/", max_tokens=800)  # estimate: 850
    assert second.status_code == 429
    body = second.json()
    assert body["error"] == "budget_exceeded"
    assert body["limit"] == "daily_tokens"
    assert 1 <= int(second["Retry-After"]) <= 86_400  # until the next UTC midnight
    assert remaining(second) >= 9_000  # the burst bucket still has plenty


def test_a_blocked_request_is_not_charged(client, llm, redis_client):
    post(client, path="/api/budgeted/", max_tokens=800, mock_completion_tokens=700)
    post(client, path="/api/budgeted/", max_tokens=800)  # blocked by the daily cap
    assert float(day_hash(redis_client, llm)["tokens"]) == pytest.approx(750)


def test_one_budget_is_shared_across_models(client, llm):
    # burst buckets are per (user, model), but the budget belongs to the user
    big = post(
        client, path="/api/budgeted/", model="large", prompt="x" * 3_000, max_tokens=0
    )
    assert big.status_code == 200  # 750 input tokens
    small = post(client, path="/api/budgeted/", model="small", max_tokens=300)
    assert small.status_code == 429  # 750 + 350 > the 1,000 daily tokens
    assert small.json()["limit"] == "daily_tokens"


def test_near_limit_alert_fires_once_on_the_final_numbers(client, llm, settings):
    events = []
    settings.TOKENGUARD["ON_NEAR_LIMIT"] = events.append
    # estimate 950 (not near 800 after settling), but really used 850 -> 85%
    post(client, path="/api/budgeted/", max_tokens=900, mock_completion_tokens=800)
    assert len(events) == 1
    event = events[0]
    assert (event["layer"], event["metric"]) == ("daily", "tokens")
    assert event["used"] == pytest.approx(850)
    assert event["fraction"] == pytest.approx(0.85)
    # already past the threshold: later requests do not raise it again
    post(client, path="/api/budgeted/", max_tokens=0, mock_completion_tokens=0)
    assert len(events) == 1


def test_no_alert_when_an_overestimate_is_refunded(client, llm, settings):
    events = []
    settings.TOKENGUARD["ON_NEAR_LIMIT"] = events.append
    # estimate 950 would look like 95%, but only 90 tokens were really used
    post(client, path="/api/budgeted/", max_tokens=900)
    assert events == []
