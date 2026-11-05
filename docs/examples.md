# Examples

Copy, paste, adjust. Each is a complete idea; they combine freely. The settings
shown go inside the `TOKENGUARD = {...}` dict in `settings.py`.

## 1. Stop password guessing on a login page

A strict rule on one path, keyed by IP, that refuses rather than allows if Redis is
down (an outage must not turn the guard off).

```python
TOKENGUARD = {
    "RULES": [
        {
            "name": "login",
            "match": r"^/login/",
            "capacity": 5,
            "refill_rate": 0.1,  # five tries, then one every 10 seconds
            "key": "ip",
            "fail_mode": "closed",
        },
    ],
}
```

## 2. An expensive endpoint costs more

Each report costs 5 tokens, so the burst of 20 allows only 4 at once.

```python
from django.http import JsonResponse
from tokenguard.django import rate_limit


@rate_limit(capacity=20, refill_rate=0.5, key="user", cost=5)
def generate_report(request):
    return JsonResponse({"report": "generated"})
```

## 3. Class-based and REST framework views

Wrap `as_view()` where the URL is declared.

```python
from django.urls import path
from rest_framework.response import Response
from rest_framework.views import APIView
from tokenguard.django import rate_limit


class SearchView(APIView):
    def get(self, request):
        return Response({"results": []})


urlpatterns = [
    path(
        "search/",
        rate_limit(capacity=30, refill_rate=1, key="user")(SearchView.as_view()),
    ),
]
```

## 4. Never limit health checks or static files

```python
TOKENGUARD = {"EXEMPT": [r"^/health/", r"^/static/"]}
```

## 5. Limit by API key, and ignore made-up keys

`api_key` gives every distinct header value its own bucket, so a client that sends a
new random key on every request is never limited. `api_key_if` only trusts keys you
recognise; everything else is limited by the sender's IP.

```python
from tokenguard.django import rate_limit
from tokenguard.django.keys import api_key_if

KNOWN_KEYS = {"k_live_abc123", "k_live_def456"}  # in real life: a cached DB lookup


@rate_limit(capacity=100, refill_rate=2, key=api_key_if(lambda raw: raw in KNOWN_KEYS))
def api(request): ...
```

## 6. Limit an LLM endpoint by tokens, not requests

The request is charged an estimate of its tokens (and its dollar cost, scaled by the
model's weight) before it runs. When the response shows the real usage, the
difference is refunded or charged. Each user gets a separate bucket per model.

```python
from tokenguard.django import rate_limit
from tokenguard.django.llm import llm_cost, llm_usage, user_model


@rate_limit(
    capacity=10_000,  # burst: 10,000 tokens
    refill_rate=50,  # sustained: 50 tokens per second
    key=user_model,
    cost=llm_cost(),
    usage=llm_usage(),
)
def complete(request): ...  # call your model; return JSON containing a usage block
```

## 7. Daily and monthly budgets, with an alert

One burst bucket per (key, model), but one budget per API key across all models.

```python
from tokenguard.budget import Budget
from tokenguard.django import rate_limit
from tokenguard.django.keys import api_key, combine
from tokenguard.django.llm import llm_cost, llm_usage, model_key

CHAT_BUDGET = Budget(daily_tokens=50_000, daily_usd=0.25, monthly_usd=5.00)


@rate_limit(
    capacity=5_000,
    refill_rate=50,
    key=combine(api_key, model_key()),
    budget_key=api_key,
    budget=CHAT_BUDGET,
    cost=llm_cost(prompt_field="messages"),
    usage=llm_usage(),
)
def chat(request): ...
```

```python
# settings.py
TOKENGUARD = {"ON_NEAR_LIMIT": "myapp.alerts.notify"}


# myapp/alerts.py
def notify(event):
    print(
        f"{event['identity']} is at {event['fraction']:.0%} of its {event['layer']} budget"
    )
```

## 8. Behind nginx or a load balancer

Without this, every client looks like the proxy and shares one bucket.

```python
TOKENGUARD = {"TRUSTED_PROXIES": ["10.0.0.0/8"]}  # your proxies only, never 0.0.0.0/0
```

Make sure the proxy appends to `X-Forwarded-For` (nginx:
`proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;`).

## 9. Change a limit without redeploying

```python
TOKENGUARD = {"LIVE_RULES": True, "LIVE_RULES_TTL": 5}
```

```python
from tokenguard.django.conf import get_rule_store

get_rule_store().set_rule(
    "login", capacity=20, refill_rate=2
)  # reaches every server in ~5 s
get_rule_store().delete_rule("login")  # back to settings.py
```

## 10. A different algorithm for one rule

A sliding window is exact (no burst at the edge of a window) but stores one entry per
request, so use it for small limits.

```python
@rate_limit(capacity=10, refill_rate=10 / 60, key="user", algorithm="sliding_window")
def send_email(request): ...  # ten per minute, counted exactly
```

## 11. Your own key

Any function from request to string. Here, one bucket per organisation.

```python
def by_org(request):
    return "org:" + request.headers.get("X-Org-Id", "none")


@rate_limit(capacity=1000, refill_rate=10, key=by_org)
def org_api(request): ...
```

## 12. Turn on metrics and the dashboard

```python
TOKENGUARD = {"METRICS": True, "METRICS_FLUSH_INTERVAL": 0.2}
```

Then see the README's Dashboard section, or `docker compose up` in a clone of the
repository.
