# Changelog

## Unreleased

Metrics (Week 6, in progress).

- `METRICS` setting: records every decision (allowed, blocked, tokens) in Redis,
  per second, per rule and per consumer, in one Lua call, with automatic expiry
  (`METRICS_RETENTION`, `METRICS_MAX_CONSUMERS`).
- `tokenguard.metrics`: `MetricsRecorder` and `MetricsReader` (`summary`,
  `timeseries`, `top_consumers`, `routes`, `bucket_level`).
- Reconcile and refund correct the recorded token counts.
- Staff-only REST API (Django REST Framework): `stats/`, `consumers/`,
  `buckets/<key>/`, `rules/` (list, change live, reset), JSON errors, exempt from
  rate limiting. Included with `tokenguard.django.api_urls`.
- WebSocket live feed (Django Channels): `ws/tokenguard/stats/`, staff-only,
  fed once a second by `manage.py tokenguard_feed` through the channel layer.
- `tokenguard.dashboard.snapshot`, `tokenguard.django.admin_api` (the framework-free
  logic behind the API), rule catalog, `scripts/ws_client.py`,
  docs/dashboard-backend.md. `dashboard` install extra.
- React dashboard (`dashboard/`, Vite + Recharts): live traffic chart over the
  WebSocket, connection state machine (connected / reconnecting / disconnected,
  0.5 s to 10 s exponential backoff, dead-socket and sign-out detection), top
  consumers, most blocked, per-rule traffic, per-key bucket gauge, and a rule
  editor that changes limits live with chart markers and a before/after readout.
  Staff sign-in endpoints (`session/`, `login/`, `logout/`). `scripts/load_demo.py`
  generates traffic; docs/dashboard.md.
- `scripts/tokenguard_stats.py` (stats, top, routes, series, bucket, watch) and
  `scripts/demo_metrics.py`; docs/metrics.md.

## 0.4.0

More algorithms, and live rule changes.

- Algorithm interface: `check(key, cost, rule) -> Decision` (plus `peek` and `adjust`),
  chosen by name with the `ALGORITHM` setting, per route (`"algorithm"` in a rule) or
  per view (`@rate_limit(..., algorithm=...)`). The token bucket is the default and
  behaves exactly as before.
- Fixed window (Lua counter) with a test that shows the 2x burst across a window edge.
- Sliding window (sorted-set log, Lua): exact, no edge burst; why a log and not the
  counter is in docs/algorithms.md.
- One contract test suite for all algorithms, run under threads and processes, and a
  comparison (docs/algorithms.md, `scripts/compare_algorithms.py`).
- Live rule changes: overrides of `capacity`, `refill_rate` and `algorithm` stored in
  Redis (atomic version counter), cached per process for `LIVE_RULES_TTL` seconds,
  applied without a redeploy. Settings `LIVE_RULES`, `LIVE_RULES_TTL`; header
  `X-TokenGuard-Rules-Version`; CLI `scripts/tokenguard_rules.py`; demo
  `scripts/demo_live_rules.py`; docs/live-rules.md.
- `X-RateLimit-Reset` is the window end for window algorithms.
- `tokenguard.__version__`, with a test that keeps it equal to `pyproject.toml`.

## 0.3.0

Token-aware limiting for LLM APIs.

- Cost model: `estimate_tokens(text, model)`, a model table with limits, prices and
  weights, a pluggable estimator (heuristic by default, tiktoken optional).
- `cost=callable(request)` on the decorator and middleware rules; requests that can
  never fit are rejected with 413 instead of 429.
- Reconciliation: atomic `adjust` Lua script refunds or charges the difference
  between estimate and real usage. Debt is bounded at one bucket.
- Per-(user, model) buckets with cost weights (the large model counts 5x).
- Budgets: burst, daily and monthly limits in tokens and dollars, checked and
  charged in one atomic Lua call. Near-limit alert hook (`ON_NEAR_LIMIT`).
- Mock chat endpoint (`/api/llm/chat/`) and a 2-minute demo (`scripts/demo_llm.py`).
- Known limitation: streaming responses (see docs/cost-model.md).

## 0.2.0

Django integration: decorator, middleware, headers, fail-open/closed modes.

## 0.1.0

Token bucket, Redis backend with atomic Lua script.
