"""The 2-minute demo: token-aware limiting on a mock LLM API.

Usage:  python scripts/demo_llm.py [http://localhost:8000]

Needs Redis and the demo server running. Standard library only. Every run uses
fresh API keys, so you can run it again and again. The script checks what it
shows and exits with an error if the limiter did not behave as expected.
"""

import json
import sys
import urllib.error
import urllib.request
import uuid

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"
RUN = uuid.uuid4().hex[:6]
CHAT = "/api/llm/chat/"
failures = []


def call(api_key, prompt="Hi!", path=CHAT, **body):
    body.setdefault("model", "small")
    if path == CHAT:
        body["messages"] = [{"role": "user", "content": prompt}]
    else:  # the older completion-style endpoints take a plain "prompt"
        body["prompt"] = prompt
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request) as response:
            status, headers, raw = response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        status, headers, raw = error.code, error.headers, error.read()
    return status, headers, json.loads(raw)


def show(who, what, result):
    status, headers, data = result
    left = headers.get("X-RateLimit-Remaining", "-")
    note = ""
    if status == 429:
        wait = headers.get("Retry-After")
        reason = data.get("limit", "burst bucket empty")
        note = f"  <- blocked ({reason}), retry in {wait}s"
    elif status == 413:
        note = f"  <- {data['cost']:,} tokens can never fit in {data['capacity']:,}"
    print(f"  {who:<8} {what:<34} {status}  tokens left: {left:>6}{note}")
    return status


def expect(label, got, wanted):
    if got != wanted:
        failures.append(f"{label}: got {got}, wanted {wanted}")


def title(text):
    print(f"\n{text}")


HUGE = "x" * 16_000  # ~4,000 tokens
MONSTER = "x" * 100_000  # ~25,000 tokens, more than the whole bucket

alice, mallory, dave = (f"{name}-{RUN}" for name in ("alice", "mallory", "dave"))
print("tokenguard demo. Burst bucket: 5,000 tokens, refilling at 50/second.")

title("1. Alice sends small prompts: all fine")
codes = []
for _ in range(5):
    codes.append(show("alice", "small prompt", call(alice, max_tokens=50)))
expect("alice small", codes, [200] * 5)

title("2. Mallory sends huge prompts (~4,000 tokens each)")
codes = []
for _ in range(3):
    result = call(mallory, HUGE, max_tokens=100)
    codes.append(show("mallory", "huge prompt", result))
expect("mallory huge", codes, [200, 429, 429])

title("3. Alice again: unaffected, she has her own bucket")
expect("alice after", show("alice", "small prompt", call(alice, max_tokens=50)), 200)

title("4. Mallory tries a monster prompt: rejected for good, not 'try later'")
expect("monster", show("mallory", "monster prompt", call(mallory, MONSTER)), 413)

title("5. Mallory's small bucket is empty, but the large model has its own")
big = call(mallory, "Short question", model="large", max_tokens=100)
expect("large model", show("mallory", "large model (counts 5x)", big), 200)

title("6. Budgets: a daily cap blocks even when the burst bucket has tokens")
first = call(dave, path="/api/budgeted/", max_tokens=800, mock_completion_tokens=700)
expect("budget 1", show("dave", "uses ~750 of 1,000 daily", first), 200)
second = call(dave, path="/api/budgeted/", max_tokens=800)
expect("budget 2", show("dave", "asks for ~850 more", second), 429)
expect("budget limit", second[2].get("limit"), "daily_tokens")

print()
if failures:
    print("DEMO CHECK FAILED:")
    for line in failures:
        print("  -", line)
    sys.exit(1)
print("Demo OK: big spenders are blocked, small users are not.")
