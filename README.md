# tokenguard

![CI](https://github.com/Shreya-724/tokenguard/actions/workflows/ci.yml/badge.svg)

A **token-aware, Redis-backed rate limiter for Django**, built for LLM APIs.
Limit clients by *how much they consume*, not just how often they call, and stay
correct when many requests arrive at once.

<!-- After recording (see docs/demo-script.md), save the GIF as docs/demo.gif and
     remove the comment markers around the image line to show it:
![The dashboard: traffic, a client hits its limit, the rule is edited live](https://raw.githubusercontent.com/Shreya-724/tokenguard/main/docs/demo.gif)
-->

## Why

A request-count limiter treats a 50-token call and a 50,000-token call the same, but
for an LLM API they cost wildly different amounts. tokenguard spends tokens from a
**token bucket**: short bursts are fine, the long-run average stays capped, and a few
huge prompts cannot use up everyone else's budget.

- **Correct under concurrency.** Each check is one Lua script, so it is atomic across
  threads, processes and servers ([the race it fixes](https://github.com/Shreya-724/tokenguard/blob/main/docs/race-condition.md)).
- **Token-aware.** Charge an estimate up front, settle with the real usage afterwards.
  Per-model buckets, plus daily and monthly budgets in tokens and dollars.
- **Three algorithms**, one interface: token bucket, fixed window, sliding window.
- **Live rules and a live dashboard.** Change a limit without a redeploy and watch
  traffic and blocks in real time.

Python 3.10 to 3.12, Django 4.2 and 5.2, Redis 7.

## Quick start (5 minutes)

You need Python 3.10+ and Docker (or any Redis you can reach). This starts from an
empty folder; nothing here needs a clone of this repository.

**1. Run Redis**

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

**2. Create a Django project and install tokenguard**

```bash
python -m venv .venv
source .venv/bin/activate            # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install "tokenguard-ratelimit[django]"   # installs as tokenguard-ratelimit, imports as tokenguard
django-admin startproject mysite
cd mysite
```

**3. Turn it on** (`mysite/settings.py`)

```python
MIDDLEWARE = [
    # ...the lines Django already put here, then, after AuthenticationMiddleware:
    "tokenguard.django.middleware.TokenGuardMiddleware",
]

TOKENGUARD = {
    "REDIS_URL": "redis://localhost:6379/0",
    "DEFAULT_RULE": {
        "capacity": 60,
        "refill_rate": 1,
    },  # burst of 60, then 1 per second
    "FAIL_MODE": "open",  # or "closed"
}
```

Every request is now limited per user (anonymous users per IP).

**4. Give one view a stricter limit** (`mysite/urls.py`)

```python
from django.http import JsonResponse
from django.urls import path
from tokenguard.django import rate_limit


@rate_limit(capacity=5, refill_rate=0.1, key="ip")  # burst of 5, then one every 10 s
def ping(request):
    return JsonResponse({"ok": True})


urlpatterns = [path("ping/", ping)]
```

**5. Try it**

```bash
python manage.py runserver
```

In a second terminal, send seven requests:

```bash
for i in 1 2 3 4 5 6 7; do curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/ping/; done
```

```powershell
1..7 | ForEach-Object { curl.exe -s -o NUL -w "%{http_code}`n" localhost:8000/ping/ }
```

You should see five `200`s, then `429` twice. Look at the refusal:

```bash
curl -i localhost:8000/ping/
```

```
HTTP/1.1 429 Too Many Requests
Retry-After: 10
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1760000010

{"error": "rate_limited", "retry_after": 9.874}
```

Wait ten seconds and one request is allowed again. That is the whole idea: a bucket
of 5 that refills at one token per 10 seconds.

**Next:** [limit by tokens for an LLM API](#limit-llm-requests-by-tokens),
[all settings](https://github.com/Shreya-724/tokenguard/blob/main/docs/configuration.md), [copy-paste examples](https://github.com/Shreya-724/tokenguard/blob/main/docs/examples.md),
[the live dashboard](#dashboard-and-demo).

## Limit LLM requests by tokens

```python
from tokenguard.budget import Budget
from tokenguard.django import rate_limit
from tokenguard.django.keys import api_key, combine
from tokenguard.django.llm import llm_cost, llm_usage, model_key


@rate_limit(
    capacity=5_000,  # burst, in tokens
    refill_rate=50,  # 50 tokens/second sustained
    key=combine(api_key, model_key()),  # a bucket per (API key, model)
    budget_key=api_key,  # one budget per API key
    cost=llm_cost(prompt_field="messages"),  # input + expected output tokens
    usage=llm_usage(),  # settle with the usage in the response
    budget=Budget(daily_tokens=50_000, daily_usd=0.25),
)
def chat(request): ...
```

The request is charged its **estimated** cost first. When the response arrives, the
real usage replaces the estimate: unused tokens are refunded and an overshoot is
charged. A request that can never fit gets `413`; one that is too much right now gets
`429` with `Retry-After`. Details, weights and budgets: [cost model](https://github.com/Shreya-724/tokenguard/blob/main/docs/cost-model.md).

## Algorithms

Pick one globally (`ALGORITHM`), per route, or per view (`@rate_limit(..., algorithm=...)`).

| | `token_bucket` (default) | `fixed_window` | `sliding_window` |
|---|---|---|---|
| Most in any window-length span | 2 x capacity | 2 x capacity (at the edge) | exactly capacity |
| Memory per key | about 120 bytes | about 120 bytes | grows with requests in the window |
| Works with budgets | yes | no | no |

Use the token bucket unless you have a reason not to. Use the sliding window for hard
limits with small numbers. More: [algorithms](https://github.com/Shreya-724/tokenguard/blob/main/docs/algorithms.md).

## Dashboard and demo

```bash
git clone https://github.com/Shreya-724/tokenguard && cd tokenguard
docker compose up --build
python scripts/load_demo.py      # from your venv: sends traffic to watch
```

| URL | What |
|---|---|
| http://localhost:8080 | the dashboard (sign in as `admin` / `admin`: a public demo password) |
| http://localhost:8000 | the demo Django site, e.g. `/api/ping/` |

The dashboard shows allowed vs blocked traffic, top consumers, each key's bucket
level, and a rule editor that changes limits live. More: [dashboard](https://github.com/Shreya-724/tokenguard/blob/main/docs/dashboard.md),
[Docker troubleshooting](https://github.com/Shreya-724/tokenguard/blob/main/docs/docker.md).

## Performance

Measured with Locust (50 users) against a real Django server on a 4-core Windows
laptop with Redis in Docker, comparing the same views with and without the limiter.
Recording metrics on the request path cost an extra Redis call. Batching it with
`METRICS_FLUSH_INTERVAL = 0.2` cut the limiter's cost per request from 1.59 ms to
0.89 ms and raised throughput by 22.6%. Your numbers will differ: reproduce them with
[benchmarks/README.md](https://github.com/Shreya-724/tokenguard/blob/main/benchmarks/README.md).

<!-- bench:start -->
Limiter cost per request: 1.59 ms before, 0.89 ms after (`--metrics-flush 0.2`);
throughput +22.6%. Run `python benchmarks/compare.py <before> <after> --readme README.md`
to regenerate this block from your own runs.
<!-- bench:end -->

Memory per key: about 112 to 128 bytes for the token bucket and fixed window; the
sliding window grows with the limit (6.2 KB at a limit of 100). See
[algorithm benchmarks](https://github.com/Shreya-724/tokenguard/blob/main/docs/algorithm-benchmarks.md).

## Documentation

| Page | What it covers |
|---|---|
| [Configuration](https://github.com/Shreya-724/tokenguard/blob/main/docs/configuration.md) | Every setting, rule fields, key functions, response headers |
| [Examples](https://github.com/Shreya-724/tokenguard/blob/main/docs/examples.md) | Twelve copy-paste recipes: login, API keys, LLM budgets, proxies |
| [Cost model](https://github.com/Shreya-724/tokenguard/blob/main/docs/cost-model.md) | Estimates, model weights, reconciliation, budgets, alerts, streaming |
| [Live rules](https://github.com/Shreya-724/tokenguard/blob/main/docs/live-rules.md) | Changing limits while the server runs |
| [Metrics](https://github.com/Shreya-724/tokenguard/blob/main/docs/metrics.md) | What is recorded and how to query it |
| [Security](https://github.com/Shreya-724/tokenguard/blob/main/docs/security.md) | Fail-open vs fail-closed, client IPs, attacks and defences |
| [Design and limits](https://github.com/Shreya-724/tokenguard/blob/main/docs/design.md) | Architecture, design decisions, known limitations |
| [Development](https://github.com/Shreya-724/tokenguard/blob/main/docs/development.md) | Running the demo and the tests |
| [All docs](https://github.com/Shreya-724/tokenguard/blob/main/docs/README.md) | The complete list |

## License

MIT. See [LICENSE](https://github.com/Shreya-724/tokenguard/blob/main/LICENSE).
