# Configuration reference

Everything is optional. With no `TOKENGUARD` setting at all you get a token bucket of
60 requests then 1 per second, per user (anonymous users per IP), on Redis at
`localhost:6379/0`, failing open.

```python
# settings.py
TOKENGUARD = {
    "REDIS_URL": "redis://localhost:6379/0",
    "DEFAULT_RULE": {"capacity": 60, "refill_rate": 1},
}
```

To see what is actually in effect (the Redis password is masked):

```python
from tokenguard.django.conf import effective_config

print(effective_config())
```

## Settings

`capacity` is the burst size. `refill_rate` is tokens per second. A request costs 1
token unless you say otherwise.

| Setting | Default | Meaning |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Where the buckets live. Use `rediss://` and a password in production. |
| `DEFAULT_RULE` | `{"capacity": 60, "refill_rate": 1}` | The rule the middleware applies to every request that has no more specific one. |
| `FAIL_MODE` | `"open"` | If Redis cannot answer: `"open"` lets the request through (and logs a warning), `"closed"` answers 503. A rule can override it. |
| `ALGORITHM` | `"token_bucket"` | `"token_bucket"`, `"fixed_window"` or `"sliding_window"`. A rule or a decorator can override it. |
| `KEY_PREFIX` | `"tg"` | Prefix for every Redis key. Change it to run several apps on one Redis. |
| `REDIS_TIMEOUT` | `0.25` | Seconds for connecting and for each command. Short on purpose: a slow Redis should not slow your site. |
| `RULES` | `[]` | Per-route rules (below). The first match wins. |
| `EXEMPT` | `[]` | Regexes for paths that are never limited (health checks, static files). |
| `TRUSTED_PROXIES` | `[]` | IPs or CIDRs allowed to set `X-Forwarded-For`. Leave empty if clients connect directly. |
| `LIVE_RULES` | `False` | Let limits be changed while the server runs, through Redis. |
| `LIVE_RULES_TTL` | `5.0` | Seconds a process caches the live rules. This is how long a change takes to spread. |
| `METRICS` | `False` | Record every decision, for the stats API and the dashboard. |
| `METRICS_RETENTION` | `3600` | Seconds of metrics history kept in Redis. |
| `METRICS_MAX_CONSUMERS` | `1000` | How many consumers are remembered per minute, per ranking. |
| `METRICS_FLUSH_INTERVAL` | `0.0` | Seconds between background metrics writes. `0` writes on the request path. About 0.2 makes the limiter cheaper per request; see the Performance section of the README. |
| `MAX_KEY_LENGTH` | `128` | A longer identity is replaced by a fixed-size hash, so a client cannot make a huge Redis key. Minimum 16. |
| `ON_NEAR_LIMIT` | `None` | A function, or its dotted path, called when a budget passes 80%. |

A bad value (an unknown algorithm, a `FAIL_MODE` of `"maybe"`) raises
`ImproperlyConfigured` the first time it is read, with a message that names the
setting.

## A rule

`DEFAULT_RULE`, every entry in `RULES`, and the arguments of `@rate_limit(...)` all
describe a rule. The fields:

| Field | In `RULES` / `DEFAULT_RULE` | In `@rate_limit` | Meaning |
|---|---|---|---|
| `capacity` | required | required | Burst size. |
| `refill_rate` | required | required | Tokens per second, sustained. |
| `name` | `RULES` only | `scope=` | Names the bucket, and is what live rules refer to. Keep it stable. |
| `match` | `RULES` only | | Regex matched from the start of the path. |
| `key` | optional | optional | Who gets a bucket: see below. Default `"user"`. |
| `cost` | optional | optional | Tokens charged. A number, a `Cost`, or a function of the request. Default 1. |
| `fail_mode` | optional | optional | Overrides `FAIL_MODE` for this rule. |
| `algorithm` | optional | optional | Overrides `ALGORITHM` for this rule. |
| `usage` | optional | optional | Function giving the tokens really used, to settle an estimate afterwards. |
| `budget` | optional | optional | Daily and monthly caps (below). In settings a plain dict works. |
| `budget_key` | optional | optional | Who owns the budget, if not the same as `key`. |

In `RULES` and `DEFAULT_RULE`, `cost`, `usage`, `key` and `budget_key` can also be a
dotted path such as `"myapp.costs.chat_cost"`.

**Precedence, highest first:** an `EXEMPT` path, then `@rate_limit` on the view, then
the first matching `RULES` entry, then `DEFAULT_RULE`. A decorated view is charged
once, by the decorator only.

## Budgets

```python
Budget(daily_tokens=50_000, daily_usd=0.25, monthly_tokens=1_000_000, monthly_usd=5.0)
```

`0` means no cap on that number. `near_limit` (default `0.8`) is the fraction at which
`ON_NEAR_LIMIT` fires. Days and months are UTC. In settings:

```python
{"budget": {"daily_tokens": 50_000, "monthly_usd": 20}}
```

## Key functions

A key function turns a request into the identity that gets its own bucket.

| Name | Bucket per |
|---|---|
| `"user"` (default) | logged-in user; anonymous users fall back to their IP |
| `"ip"` | client IP (see `TRUSTED_PROXIES`) |
| `"api_key"` | the `X-API-Key` header, stored hashed |
| `"endpoint"` | URL pattern, shared by everyone |
| `"user_endpoint"` | user and endpoint |
| `"tokenguard.django.llm.user_model"` | user and model name (LLM bodies) |

Or pass any function `f(request) -> str`, a dotted path to one, or build one with
`tokenguard.django.keys.combine(a, b)`. Use `api_key_if(check)` instead of `api_key`
when keys can be made up by the client; unknown keys then share the sender's IP bucket.

## Response headers

| Header | When | Meaning |
|---|---|---|
| `X-RateLimit-Limit` | every response | Bucket capacity |
| `X-RateLimit-Remaining` | every response | Whole tokens left |
| `X-RateLimit-Reset` | every response | Unix time when the limit is full again |
| `Retry-After` | 429 only | Whole seconds to wait, rounded up |
| `X-TokenGuard-Rules-Version` | `LIVE_RULES` on | Version of the live rules that served the request |

If Redis is down and the limiter fails open, no `X-RateLimit-*` headers are sent, since
no decision was made.

## Extras (what `pip install` pulls in)

| Install | Adds |
|---|---|
| `tokenguard-ratelimit` | the limiter and its algorithms (needs `redis`) |
| `tokenguard-ratelimit[django]` | the middleware and `@rate_limit` |
| `tokenguard-ratelimit[drf]` | the staff-only metrics and rules API |
| `tokenguard-ratelimit[dashboard]` | the WebSocket feed (channels, daphne) |
