import json
import uuid

import pytest

pytest.importorskip("django")

from tokenguard.django.llm import llm_cost, llm_usage  # noqa: E402

CAPACITY = 10_000  # the /api/complete/ view in demo_site/views.py


@pytest.fixture
def rf():
    from django.test import RequestFactory

    return RequestFactory()


def json_request(rf, body):
    return rf.post("/x", data=json.dumps(body), content_type="application/json")


# ---- cost function (no Redis needed) ----
def test_llm_cost_is_input_plus_output(rf):
    req = json_request(rf, {"model": "small", "prompt": "x" * 400, "max_tokens": 50})
    assert llm_cost()(req) == 150


def test_llm_cost_uses_model_default_output(rf):
    req = json_request(rf, {"model": "large", "prompt": "x" * 400})
    assert llm_cost()(req) == 100 + 512


def test_llm_cost_understands_chat_messages(rf):
    body = {"messages": [{"role": "user", "content": "x" * 40}], "max_tokens": 0}
    assert llm_cost(prompt_field="messages")(json_request(rf, body)) == 10


def test_llm_cost_bad_json_is_cheap_not_a_crash(rf):
    req = rf.post("/x", data="{not json", content_type="application/json")
    assert llm_cost()(req) == 1


def test_llm_cost_ignores_nonsense_max_tokens(rf):
    req = json_request(rf, {"prompt": "x" * 400, "max_tokens": "lots"})
    assert llm_cost()(req) == 100 + 256


def test_llm_usage_reads_total_or_parts():
    class R:
        def __init__(self, content):
            self.content = content

    usage = llm_usage()
    assert usage(None, R(b'{"usage": {"total_tokens": 90}}')) == 90
    parts = b'{"usage": {"prompt_tokens": 50, "completion_tokens": 40}}'
    assert usage(None, R(parts)) == 90
    assert usage(None, R(b'{"error": "nope"}')) is None
    assert usage(None, R(b"not json")) is None


# ---- end to end through the demo endpoint (needs Redis) ----
@pytest.fixture
def llm(settings, redis_client, redis_url):
    prefix = f"tgllm-{uuid.uuid4().hex[:8]}"
    settings.TOKENGUARD = {"REDIS_URL": redis_url, "KEY_PREFIX": prefix}
    yield
    for k in redis_client.scan_iter(f"{prefix}:*"):
        redis_client.delete(k)


def post(client, ip="10.0.0.1", **body):
    body.setdefault("model", "small")
    body.setdefault("prompt", "x" * 200)  # 50 tokens
    return client.post(
        "/api/complete/",
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
    r = client.post(
        "/api/complete-manual/",
        data=json.dumps({"prompt": "x" * 200, "max_tokens": 1000}),
        content_type="application/json",
        REMOTE_ADDR="10.0.0.9",
    )
    assert abs(remaining(r) - 9_910) <= 5
