# tokenguard

![CI](https://github.com/<your-username>/tokenguard/actions/workflows/ci.yml/badge.svg)

A **token-aware, Redis-backed rate limiter for Django**, built for LLM APIs.
Limit clients by *how much they consume*, not just how often they call, with
atomic correctness under concurrency.

> **Status: work in progress (v0.5.0).** The core limiter, Redis/Lua backend, Django
> integration, token-aware LLM limiting with budgets, three algorithms, live rule
> changes, metrics and a live React dashboard are done. Load tests and hardening are
> next (see [Roadmap](#roadmap)).

<!-- After recording (see docs/demo-script.md), save the GIF as docs/demo.gif and
     remove the comment markers around the image line to show it:
![The dashboard: traffic, a client hits its limit, the rule is edited live](docs/demo.gif)
-->

## Why

Plain request-count limiters treat a 50-token call and a 50,000-token call the same,
but for an LLM API they cost wildly different amounts. tokenguard is built around a
**token bucket**: each request spends tokens, and the bucket refills at a steady
rate, so short bursts are fine while the long-run average stays capped.

## Features

- Token bucket with burst capacity, fractional refill, `retry_after` and `peek()`
- **Atomic Redis backend** (one Lua script), correct across threads, processes and servers
- Django **decorator** (function views, class-based views, DRF) and **middleware**
- Per-route rules, an exempt list, and clear precedence
- Standard headers: `X-RateLimit-*` on every response, `Retry-After` on 429s
- **Fail-open / fail-closed** when Redis is unreachable, configurable per rule
- Key functions: per user, IP, API key, endpoint, or any combination
- Safe client-IP handling (`X-Forwarded-For` is only trusted behind known proxies)
- **Token-aware LLM limiting**: charge by estimated tokens, then settle with the real
  usage (refund or charge the difference)
- **Per-model buckets and cost weights** (the large model can count 5x)
- **Budgets**: burst, daily and monthly limits in tokens *and dollars*, checked in one
  atomic Lua call, with a near-limit alert hook
- **Three algorithms behind one interface** (token bucket, fixed window, sliding
  window), chosen globally, per route or per view
- **Live rule changes**: change a limit while the server runs, with no redeploy
- **Metrics**: every decision recorded in Redis (one Lua call), queryable for
  requests/sec, blocked ratio, top consumers and a key's bucket level
- **Live dashboard** (React + Recharts over a WebSocket): traffic chart, top consumers,
  bucket gauge, and a rule editor that shows the before/after of a change

## Quick start (5 minutes)

**1. Run Redis**

```bash
docker compose up -d
```

**2. Install**

```bash
pip install "tokenguard[django]"      # add [drf] for Django REST Framework
```

**3. Configure Django** (`settings.py`)

```python
MIDDLEWARE = [
    # ...
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "tokenguard.django.middleware.TokenGuardMiddleware",  # after authentication
]

TOKENGUARD = {
    "REDIS_URL": "redis://localhost:6379/0",
    "DEFAULT_RULE": {"capacity": 60, "refill_rate": 1},  # burst of 60, then 1/sec
    "FAIL_MODE": "open",  # or "closed"
    "KEY_PREFIX": "tg",
}
```

Every request is now limited per user (anonymous users per IP).

**4. Limit a single view**

```python
from tokenguard.django import rate_limit


@rate_limit(capacity=20, refill_rate=0.5, key="user", cost=5)
def generate_report(request): ...
```

**5. Try it**

```bash
curl -i localhost:8000/login/     # repeat 6 times: the 6th is a 429
```

```
HTTP/1.1 429 Too Many Requests
Retry-After: 10
X-RateLimit-Limit: 5
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1760000010

{"error": "rate_limited", "retry_after": 9.874}
```

## Token-aware limiting for LLM APIs

A request is charged by what it is expected to cost, not as "1 request":

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
    budget=Budget(
        daily_tokens=50_000, daily_usd=0.25, monthly_tokens=1_000_000, monthly_usd=5.00
    ),
)
def chat(request): ...
```

**1. Estimate and charge up front.** `cost = estimated input tokens + expected output
tokens` (about 4 characters per token, or plug in tiktoken with `set_estimator`). The
output is whatever `max_tokens` allows, or the model's default. The model table
(`tokenguard.llm.MODELS`) holds each model's limits, prices and weight.

**2. Reject what can never fit.** A request that costs more than the bucket (or a
budget) can ever hold gets `413 request_too_large` with no `Retry-After`: waiting would
not help, the caller must send less. Everything else that is too much *right now* gets
`429` with a `Retry-After`.

**3. Reconcile after the call.** The response's real usage replaces the estimate: an
unused part is refunded, an overshoot is charged. Overspend may put the bucket into
*debt*, capped at one bucket's worth, so a single huge reply delays the next request
but cannot lock a user out for hours. Server errors (5xx) and crashed views are
refunded in full; client errors (4xx) stay charged. Details and every edge case:
[docs/cost-model.md](docs/cost-model.md).

**4. Weights and isolation.** Each `(user, model)` pair has its own bucket, and a model
can have a weight: with `large` at 5x, 2,000 tokens cost 10,000 bucket tokens. Heavy
use of the large model never blocks the small one.

**5. Budgets, all or nothing.** Daily and monthly caps (UTC) in tokens and dollars sit
on top of the burst bucket. One Lua script checks and charges every layer together, so
a request is never half-charged, and exceeding the daily cap blocks a request even when
the burst bucket still has tokens:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 41230

{"error": "budget_exceeded", "limit": "daily_tokens", "retry_after": 41230}
```

**6. Near-limit alerts.** When a budget crosses 80% (`Budget(near_limit=0.8)`), tokenguard logs a warning and
calls your hook once:

```python
TOKENGUARD = {
    # ...
    "ON_NEAR_LIMIT": "myapp.alerts.notify",  # or any callable(event: dict)
}


def notify(event):
    # {"scope": ..., "identity": ..., "layer": "daily", "metric": "tokens",
    #  "used": 41_000, "limit": 50_000, "fraction": 0.82}
    send_slack(f"{event['identity']} is at {event['fraction']:.0%} of its daily budget")
```

Alerts use the numbers *after* reconciliation, so an over-cautious estimate that was
refunded a moment later does not raise a false alarm.

### Try it: the 2-minute demo

```bash
docker compose up -d
python demo/manage.py runserver          # terminal 1
python scripts/demo_llm.py               # terminal 2
```

The demo talks to a fake chat API (`/api/llm/chat/`, canned text plus a `usage` block):

```
1. Alice sends small prompts: all fine
  alice    small prompt                       200  tokens left:   4959
2. Mallory sends huge prompts (~4,000 tokens each)
  mallory  huge prompt                        200  tokens left:    960
  mallory  huge prompt                        429  tokens left:    960  <- blocked (burst bucket empty), retry in 63s
3. Alice again: unaffected, she has her own bucket
4. Mallory tries a monster prompt: rejected for good, not 'try later'
  mallory  monster prompt                     413  <- 25,000 tokens can never fit in 5,000
5. Mallory's small bucket is empty, but the large model has its own
6. Budgets: a daily cap blocks even when the burst bucket has tokens
```

(Replace this block with your own real output after running it.)

### Known limitation: streaming

With streamed responses the real usage only arrives in the last chunk, after the
response has started. tokenguard can then only keep the up-front estimate, unless your
code calls `request.tokenguard.reconcile(usage)` when the stream ends. Settling
automatically at the end of a stream is future work.

## Algorithms: which one should I use?

tokenguard has three algorithms behind one interface. Pick one globally with
`TOKENGUARD["ALGORITHM"]`, per route with `"algorithm"` in a rule, or per view with
`@rate_limit(..., algorithm="...")`.

| | `token_bucket` (default) | `fixed_window` | `sliding_window` |
|---|---|---|---|
| Most in any window-length span | 2 x capacity | 2 x capacity (at the edge) | exactly capacity |
| Memory per key | 120 bytes | 120 bytes | ~130 bytes per request in the window |
| Time per check | O(1) | O(1) | O(requests in the window) |
| Works with budgets | yes | no | no |

- **Token bucket**: the default. Cheapest, bursts on purpose, and the only one that
  works with budgets and settled LLM token costs.
- **Fixed window**: simplest to explain, but a client can use two windows' worth
  around an edge.
- **Sliding window**: never more than the limit in any span. Use it for hard limits
  with small numbers (tens of requests per key), since memory and time grow with the
  requests in the window.

Details, the boundary-burst demonstration and reproducible numbers:
[docs/algorithms.md](docs/algorithms.md). Run `python scripts/compare_algorithms.py`
to measure them on your own machine.

## Live rule changes

Change a limit while the server runs, with no redeploy. Rules live in Redis, every
process caches them for a few seconds, and each change bumps a version number.

```python
TOKENGUARD = {"LIVE_RULES": True, "LIVE_RULES_TTL": 5}  # off by default
```

```bash
python scripts/tokenguard_rules.py set login --capacity 20 --refill-rate 2
python scripts/tokenguard_rules.py delete login          # back to the settings
```

- A change reaches every server within `LIVE_RULES_TTL` seconds, and requests never
  wait on Redis for it (they read the cached copy).
- You can change `capacity`, `refill_rate` and `algorithm` of the default rule, a
  `RULES` entry, or a decorated view. Responses show the version in
  `X-TokenGuard-Rules-Version`.
- If Redis is down the last known rules keep being used. Bad values are rejected,
  and an override that cannot apply is ignored.

Details, what happens to existing counters, and a demo (`scripts/demo_live_rules.py`):
[docs/live-rules.md](docs/live-rules.md).

## Metrics

Turn on `"METRICS": True` and tokenguard records every decision in Redis (one
Lua call each): allowed and blocked per second, per rule, and per consumer, with
automatic expiry. Then ask it questions:

```python
from tokenguard.django.conf import get_metrics_reader

m = get_metrics_reader()
m.summary(60)  # requests, blocked ratio, requests/sec
m.top_consumers(n=5)  # who is using the most right now
m.timeseries(seconds=300)  # per second, for a chart
```

or `python scripts/tokenguard_stats.py top`. Details, storage layout and limits:
[docs/metrics.md](docs/metrics.md).

## Dashboard

A React dashboard (`dashboard/`) shows live traffic over the WebSocket: an
allowed-vs-blocked chart, top consumers, per-key bucket levels, and a rule
editor that changes limits live and shows the before/after. Run it with
`npm install && npm run dev` in `dashboard/`, next to the Django server and
`manage.py tokenguard_feed`. Details: [docs/dashboard.md](docs/dashboard.md).

## Configuration reference

| Setting | Default | Meaning |
|---|---|---|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL |
| `DEFAULT_RULE` | `{"capacity": 60, "refill_rate": 1}` | Rule applied to every request by the middleware |
| `FAIL_MODE` | `"open"` | What to do if Redis is down: `"open"` or `"closed"` |
| `ALGORITHM` | `"token_bucket"` | `"token_bucket"`, `"fixed_window"` or `"sliding_window"`; a rule can override it |
| `LIVE_RULES` | `False` | Allow rules to be changed live in Redis |
| `LIVE_RULES_TTL` | `5` | Seconds a process caches the live rules (the propagation delay) |
| `KEY_PREFIX` | `"tg"` | Prefix for all Redis keys |
| `REDIS_TIMEOUT` | `0.25` | Seconds for Redis connect and each command |
| `RULES` | `[]` | Per-route overrides (below); first match wins |
| `EXEMPT` | `[]` | Regexes for paths that are never limited |
| `TRUSTED_PROXIES` | `[]` | IPs/CIDRs allowed to set `X-Forwarded-For` |
| `METRICS` | `False` | Record every decision for the dashboard and the stats API |
| `METRICS_RETENTION` | `3600` | Seconds of metrics history kept in Redis |
| `METRICS_MAX_CONSUMERS` | `1000` | Consumers kept per minute, per ranking |
| `ON_NEAR_LIMIT` | `None` | Callable (or dotted path) called when a budget passes 80% |

`capacity` is the burst size, `refill_rate` is tokens per second.

**Per-route rules**

```python
TOKENGUARD = {
    "EXEMPT": [r"^/health/", r"^/static/"],
    "RULES": [
        {
            "name": "login",  # names the bucket; keep it stable
            "match": r"^/login/",  # matched from the start of the path
            "capacity": 5,
            "refill_rate": 0.1,  # one new attempt every 10 seconds
            "key": "ip",
            "fail_mode": "closed",
        },
    ],
}
```

**Precedence, highest first:** exempt path, then `@rate_limit` on the view, then the
first matching `RULES` entry, then `DEFAULT_RULE`. A decorated view is charged once,
by the decorator only.

## Key functions

A key function turns a request into the identity that gets its own bucket.

| Name | Bucket per | Example |
|---|---|---|
| `"user"` (default) | logged-in user, anonymous users fall back to IP | `user:42` |
| `"ip"` | client IP | `ip:203.0.113.7` |
| `"api_key"` | API key from `X-API-Key` (stored hashed) | `apikey:9f2c...` |
| `"endpoint"` | URL pattern, shared by everyone | `/api/chat/` |
| `"user_endpoint"` | user and endpoint | `user:42:/api/chat/` |

Use any callable too: `key=lambda request: request.headers["X-Org-Id"]`, or a dotted
path string. Combine built-ins with `tokenguard.django.keys.combine(...)`.

## Response headers

| Header | On | Meaning |
|---|---|---|
| `X-RateLimit-Limit` | all responses | Bucket capacity |
| `X-RateLimit-Remaining` | all responses | Whole tokens left |
| `X-RateLimit-Reset` | all responses | Unix time when the limit is full again (for a fixed window: when the window ends) |
| `X-TokenGuard-Rules-Version` | when `LIVE_RULES` is on | Version of the live rules that served the request |
| `Retry-After` | 429 only | Whole seconds to wait, rounded up (for a budget: until the next UTC midnight or month) |

If Redis is down and the limiter fails open, no `X-RateLimit-*` headers are sent
(no decision was made).

## Fail-open vs fail-closed

If Redis is unreachable (timeouts are short, `REDIS_TIMEOUT`):

- **`open`**: the request goes through and a warning is logged. Choose this for
  public reads, where availability matters more than a few extra requests.
- **`closed`**: the request gets `503`. Choose this where abuse is costly: login
  endpoints (brute force), expensive or paid operations.

Set a global default with `FAIL_MODE` and override it per rule or decorator with
`fail_mode=`.

## Client IP and `X-Forwarded-For`

`X-Forwarded-For` is a normal header, so any client can send a fake one. If it were
trusted blindly, an attacker could rotate fake IPs and never be limited.
tokenguard **ignores it** unless the direct peer is listed in `TRUSTED_PROXIES`. It
then reads the header from the right and takes the first address that is not one of
your own proxies.

## How a token bucket works

A bucket holds up to `capacity` tokens and refills at `refill_rate` per second. Each
request spends tokens. If the bucket has enough, the request is allowed; otherwise it
is rejected with a `retry_after`.

Example with capacity 10 and refill 1/sec:

- t=0: 10 tokens. 10 requests arrive together, all allowed, 0 left
- t=0: an 11th request is rejected, `retry_after` = 1.0s
- t=3: 3 tokens have refilled, so a cost-3 request is allowed
- t=1h: the bucket is back to 10, never more (capped at capacity)

Bursts are allowed up to `capacity`, while the long-run average is limited to
`refill_rate`.

**Why not a fixed window?** A fixed window lets a client send a full quota at the end
of one window and another at the start of the next, doubling the limit in a short
span. A token bucket refills smoothly, so the limit holds over any time span while
still allowing controlled bursts. It also needs only two numbers per client (tokens
and last-refill time), which makes it cheap to store in Redis.

## Architecture

```
request -> Django middleware / @rate_limit -> live rule override (cached, optional)
        -> key function -> algorithm: token bucket | fixed window | sliding window
                                          |
                             one Lua script per check, atomic
                                          |
                                        Redis
```

- **In-memory `TokenBucket`**: single process, used for tests and as the reference
  implementation. Uses an injectable clock, so tests never call `sleep`.
- **`RedisTokenBucket`**: shared by every process and server. One Redis hash per
  bucket (`tokens`, `ts`), with a TTL so idle buckets disappear.
- Both implementations run the **same test suite**, so they are guaranteed to agree.
- **Algorithms** (`tokenguard.algorithms`) share one interface, `check(key, cost, rule)`,
  and one contract test suite that every algorithm must pass, including an exact-count
  test under many threads and many processes.
- **`RuleStore`** (`tokenguard.rulestore`) keeps live rule overrides in one Redis hash
  with an atomic version counter, and caches them per process.
- **Metrics** (`tokenguard.metrics`): `MetricsRecorder` writes one Lua call per decision
  (per-second counters in a per-minute hash, plus two sorted sets for top consumers);
  `MetricsReader` answers the questions. Everything expires on its own.
- **Dashboard path**: staff-only REST API (DRF) and a WebSocket (Channels). A separate
  `tokenguard_feed` process computes one snapshot per second and fans it out through
  the channel layer, so Redis does the same work for one viewer or fifty.

## Correctness under concurrency

My first Redis version read the bucket, calculated in Python and wrote it back. Under
concurrency, two requests could read the same token count before either wrote back,
so both spent the same token. This is a check-then-act race.

1,000 requests against a bucket with capacity 100:

| Implementation | Threads (50) | Processes (8) |
|---|---|---|
| Naive (read, compute, write) | `<N>` allowed | `<N>` allowed |
| Atomic Lua script | exactly 100, every run | exactly 100, every run |

The fix moves the whole read-compute-write into one Lua script, which Redis executes
atomically. See [docs/race-condition.md](docs/race-condition.md) for the reproduction.

## Design decisions

- **Lua script for atomicity.** One round trip, and no other client can run between
  the read and the write. Downside: logic lives in a second language that is harder
  to debug and test, and a slow script blocks Redis.
- **Redis `TIME` for the clock.** All app servers share one clock, so clock skew
  between servers cannot create or destroy tokens. (Tests can pass a fake clock.)
- **Fail-open / fail-closed is configurable**, because the right answer differs by
  endpoint.
- **`endpoint` keys use the URL pattern, not the raw path**, so `/items/1` and
  `/items/2` share a bucket and attackers cannot mint endless buckets.
- **API keys are hashed** before they become part of a Redis key.
- **Charge an estimate, then reconcile.** The real token count is only known after the
  model answers, but the limit must be enforced before it runs. So tokenguard charges a
  pessimistic estimate up front and settles the difference afterwards.
- **Bounded debt, not clamp-to-zero.** Clamping would let a user send one enormous reply
  for free; unbounded debt could lock them out for hours. The floor is one bucket.
- **One Lua call for all layers.** Burst, daily and monthly counters share a Redis Cluster
  hash tag and are checked and charged together, so a rejected request leaves no trace.
- **The engine applies model weights**, so views and usage hooks only ever deal with
  raw tokens.
- **Metrics in Redis, not in process memory.** Every worker and server sees the same
  numbers, and nothing is lost when one restarts. The price is one Lua call per
  decision, which Week 7 measures.
- **One feed process, not one loop per connection.** The snapshot is computed once a
  second and broadcast, so load on Redis does not grow with the number of viewers.
- **The connection is an explicit state machine** (connected, reconnecting,
  disconnected) with doubling, capped backoff, so the UI never guesses; it is
  tested without a browser using a fake socket and a fake clock.
- **A sliding-window log, not the cheaper counter.** The counter assumes traffic was
  spread evenly through the last window, so a burst packed at a window's end can still
  slip nearly double through. The log is exact, and costs memory and time proportional
  to the requests in the window, which is why it is recommended for small limits only.
- **One rule, two numbers.** Every algorithm takes `capacity` and `refill_rate`; window
  algorithms read them as "capacity per capacity/refill_rate seconds", so switching
  algorithm keeps the long-run average.
- **Live rules are cached, not fetched per request.** A request never waits on Redis for
  its rule: each process refreshes at most every `LIVE_RULES_TTL` seconds, keeps the last
  known rules if Redis is down, and ignores damaged or inapplicable overrides.

## Running the demo and tests

The dashboard and its traffic generator are covered in [docs/dashboard.md](docs/dashboard.md)
and [docs/demo-script.md](docs/demo-script.md) (a 60-second walkthrough).

```bash
git clone https://github.com/<your-username>/tokenguard && cd tokenguard
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d

python demo/manage.py runserver        # then try the curl above
pytest                                 # unit, shared, concurrency and Django tests
python scripts/latency.py              # per-call latency (localhost Redis)
python scripts/demo_llm.py             # the LLM demo (server must be running)
python scripts/compare_algorithms.py   # edge burst, memory and speed per algorithm
python scripts/demo_live_rules.py      # change a limit live (needs LIVE_RULES on)
python scripts/tokenguard_rules.py list    # inspect or change live rules
python scripts/tokenguard_stats.py top     # who is using the most right now
python scripts/load_demo.py                # traffic for the dashboard
python scripts/demo_check.py               # is everything up for a demo?
python demo/manage.py tokenguard_feed      # feeds the dashboard (WebSocket)
(cd dashboard && npm install && npm run dev && npm test)   # the React dashboard
```

Demo endpoints: `/api/ping/` (default rule), `/api/report/` (decorator, costs 5
tokens), `/login/` (route rule, fail-closed), `/api/chat/` (DRF view),
`/health/` (exempt), `/api/config/` (shows the active settings), `/api/fixed/` (a
fixed-window view), `/api/keyed/` (one bucket per `X-API-Key`), `/api/summary/` (class-based view), and the mock LLM API: `/api/llm/chat/`, `/api/complete/`, `/api/complete-manual/`, `/api/budgeted/`.

## Limitations

- Django views must be synchronous (async views are not supported yet).
- With `open` mode and Redis down, each request waits up to `REDIS_TIMEOUT` before
  being let through; there is no circuit breaker yet.
- For DRF views that authenticate inside DRF (token or JWT) and need per-user limits,
  decorate the handler method and add the path to `EXEMPT` so the middleware does not
  charge it too. The decorator is only auto-detected on the view function itself,
  for example when it wraps `as_view()` in `urls.py` or `dispatch` via
  `method_decorator`.
- Single Redis node; Redis Cluster is untested (keys use hash tags, so it should work).
- Streaming responses are only settled if your code calls `reconcile` itself.
- Token counts are an estimate (about 4 characters per token) unless you plug in a real
  tokenizer, and prices in the model table are illustrative: use your provider's.
- Budget periods are UTC days and months.
- Budgets use the token bucket: they cannot be combined with `fixed_window` or
  `sliding_window` on the same rule.
- The sliding window stores one Redis entry per request in the window, so it suits
  small limits (tens per key), not thousands.
- Live rule changes: there is a delay of up to `LIVE_RULES_TTL` seconds, anyone who can
  write to Redis can change limits (protect it), and the rules hash must not be evicted.
  The staff-only rules API and dashboard are the authenticated way to change them.
- Metrics cost one extra Redis call per limited request (Week 7 measures it). Each
  minute keeps at most `METRICS_MAX_CONSUMERS` consumers per ranking, so a long tail
  of one-off keys may be missing from the top lists. Times come from the app server's
  clock.
- Dashboard: the "most blocked" panel is a ranking per key, not a log of requests;
  bucket levels are not available for budgeted rules; chart history lives in the
  browser tab; it needs the `tokenguard_feed` process running to update.

## Roadmap

- [x] Week 1: in-memory token bucket, fake clock, CI
- [x] Week 2: Redis + atomic Lua, race condition proven and fixed
- [x] Week 3: Django decorator, middleware, headers, fail modes
- [x] Week 4: LLM token-aware charging, per-model buckets, budgets, mock LLM demo
- [x] Week 5: three algorithms behind one interface, live rule changes
- [x] Week 6: metrics, staff REST API, WebSocket feed, React dashboard
- [ ] Week 7: load tests and hardening
- [ ] Week 8: PyPI release and write-up
