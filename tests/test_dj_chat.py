"""The mock chat endpoint (/api/llm/chat/) and the story the demo tells."""

import json
import uuid

import pytest

pytest.importorskip("django")
pytest.importorskip("rest_framework")

CHAT = "/api/llm/chat/"
HUGE = "x" * 16_000  # about 4,000 tokens
BUCKET = 5_000


@pytest.fixture
def ns(settings, redis_client, redis_url):
    prefix = f"tgchat-{uuid.uuid4().hex[:8]}"
    settings.TOKENGUARD = {"REDIS_URL": redis_url, "KEY_PREFIX": prefix}
    yield prefix
    for k in redis_client.scan_iter(f"{prefix}:*"):
        redis_client.delete(k)


def chat(client, api_key, prompt="Hi!", **body):
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


def test_the_response_looks_like_a_chat_completion(client, ns):
    r = chat(client, "a", max_tokens=50)
    assert r.status_code == 200
    data = r.json()
    assert data["choices"][0]["message"]["role"] == "assistant"
    usage = data["usage"]
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]
    assert r["X-RateLimit-Limit"] == str(BUCKET)


def test_a_small_prompt_barely_dents_the_bucket(client, ns):
    r = chat(client, "a", max_tokens=50)  # really uses a few dozen tokens
    assert remaining(r) >= BUCKET - 100


def test_a_huge_prompt_is_blocked_after_the_first(client, ns):
    first = chat(client, "mallory", HUGE, max_tokens=100)
    assert first.status_code == 200
    assert remaining(first) < 1_100  # about 4,040 of 5,000 really used
    second = chat(client, "mallory", HUGE, max_tokens=100)
    assert second.status_code == 429
    assert second.json()["error"] == "rate_limited"
    assert 55 <= int(second["Retry-After"]) <= 66  # (4,100 - ~960) / 50 per second


def test_a_heavy_user_does_not_block_a_light_one(client, ns):
    chat(client, "mallory", HUGE, max_tokens=100)
    assert chat(client, "mallory", HUGE, max_tokens=100).status_code == 429
    assert chat(client, "alice", max_tokens=50).status_code == 200


def test_the_same_key_gets_a_separate_bucket_per_model(client, ns):
    chat(client, "mallory", HUGE, max_tokens=100)
    assert chat(client, "mallory", HUGE, max_tokens=100).status_code == 429
    large = chat(client, "mallory", "Short question", model="large", max_tokens=100)
    assert large.status_code == 200  # the large model has its own bucket
    assert abs(remaining(large) - (BUCKET - 5 * 44)) <= 10  # counts 5x: 44 tokens


def test_a_monster_prompt_is_413_and_costs_nothing(client, ns):
    r = chat(client, "mallory", "x" * 100_000)  # about 25,000 tokens
    assert r.status_code == 413
    assert r.json()["error"] == "request_too_large"
    assert "Retry-After" not in r
    assert remaining(chat(client, "mallory", max_tokens=0)) >= BUCKET - 50


@pytest.mark.parametrize(
    "payload",
    [
        {"messages": "hello"},  # not a list
        {"messages": []},  # empty
        {"messages": [{"role": "user"}]},  # no content
        {"messages": [{"role": "user", "content": 5}]},  # content not a string
        {"messages": [{"role": "user", "content": "hi"}], "model": "nope"},
    ],
)
def test_bad_requests_get_a_400(client, ns, payload):
    r = client.post(
        CHAT,
        data=json.dumps(payload),
        content_type="application/json",
        HTTP_X_API_KEY="a",
    )
    assert r.status_code == 400


def test_invalid_json_gets_a_400(client, ns):
    r = client.post(
        CHAT, data="{nope", content_type="application/json", HTTP_X_API_KEY="a"
    )
    assert r.status_code == 400


def test_the_daily_budget_is_shared_across_models(client, ns):
    # Daily cap: 50,000 tokens per API key. Each request below is admitted on a
    # small estimate, then settles to the ~30,000 tokens it really used.
    first = chat(client, "big", max_tokens=100, mock_completion_tokens=30_000)
    assert first.status_code == 200
    large = {"model": "large", "max_tokens": 100, "mock_completion_tokens": 30_000}
    assert chat(client, "big", **large).status_code == 200  # its own burst bucket
    third = chat(client, "big", max_tokens=100)  # ~60,000 used so far today
    assert third.status_code == 429
    assert third.json()["error"] == "budget_exceeded"
    assert third.json()["limit"] == "daily_tokens"
