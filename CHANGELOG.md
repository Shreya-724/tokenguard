# Changelog

## 1.0.0

First release on PyPI. The API is considered stable from here: changes that break
it will wait for 2.0.

- Installs as `tokenguard-ratelimit` (imports as `tokenguard`). MIT license.
- Wheel and sdist metadata: classifiers, URLs, `py.typed`, extras `django`, `drf`,
  `dashboard`, `bench`, `dev`.
- `scripts/release_check.py` checks metadata, wheel contents and a clean install;
  `scripts/set_github_user.py` fills in the repository URLs. See `docs/releasing.md`.
- A tag `vX.Y.Z` builds, checks and publishes the release (`.github/workflows/release.yml`).
- CI builds the package, installs the wheel in a fresh virtualenv, and tests against
  Django 4.2 and 5.2.

### Documentation

- A quick start that begins in an empty folder: new Django project, install from PyPI,
  one decorated view, and the expected `200 200 200 200 200 429 429`.
  `scripts/quickstart_check.py` runs those exact steps, and `release_check.py install`
  runs it inside the fresh virtualenv it builds.
- `docs/configuration.md` (every setting, rule field, key function and header),
  `docs/examples.md` (twelve recipes) and `docs/race-condition.md`.
- `scripts/race_demo.py` reproduces the check-then-act race: the naive limiter lets
  through several times the limit, every Lua algorithm exactly the limit.
- `tests/test_docs.py` fails if a setting is missing from the README or the reference,
  or an example stops being valid Python.

## 0.6.0

Proof, performance and hardening.

### Fixed

- **Sliding window: a refund left a key with no expiry.** Settling a request for
  less than was estimated removed the last log entry (which deletes the key) and
  re-added it without a TTL, so every refunded request leaked a key that never
  expired. Fixed in `sliding_window_adjust.lua`. If you ran an earlier version with
  `sliding_window`, find and repair leftovers with
  `python scripts/tokenguard_audit.py --fix`.
- Redis "cannot answer" failures other than a dead connection (`OOM` with
  `noeviction`, `READONLY`, `BUSY`, `MASTERDOWN`, `LOADING`) used to surface as an
  unhandled error. They now count as "Redis unavailable", so `FAIL_MODE` decides.
- Percentiles in the benchmark scripts used banker's rounding; now nearest-rank.

### Added

- `MAX_KEY_LENGTH` (default 128): a longer identity is replaced by a fixed-size hash
  of it, so a client cannot make a huge Redis key. `tokenguard.identity`.
- `tokenguard.django.keys.api_key_if(check)`: limit only API keys you recognise;
  made-up ones fall back to the IP bucket.
- `METRICS_FLUSH_INTERVAL`: write metrics in batches from a background thread
  instead of one Redis call per request (off by default). Measured on the author's
  machine: about 23% more requests per second, and the limiter's cost per request
  down from about 1.6 ms to 0.9 ms.
- `scripts/tokenguard_audit.py`: counts keys, estimates their memory, finds keys
  that never expire, and repairs them with `--fix`.
- `benchmarks/`: a repeatable Locust load test (allowed, blocked and distinct-caller
  scenarios) that runs the same views with and without the limiter; `report.py`,
  `compare.py` (before/after table for the README), `profile_limiter.py` (round trips
  and time per decision), `limiter_bench.py`, `algo_bench.py` (speed and memory per
  key for the three algorithms, with a chart), `key_flood.py` (what a flood of
  one-off callers does to Redis under each eviction policy) and `smoke_check.py`.
- `docker compose up --build` starts Django, Redis (256 MB, `volatile-lru`) and the
  dashboard behind nginx. See `docs/docker.md`.
- CI: lint, unit tests, concurrency tests, an end-to-end run, a Locust smoke load
  test, the dashboard build, and a Docker job that starts the whole stack.
- README: Performance and Security considerations sections.

## 0.5.0

Metrics, a staff-only API and a live React dashboard.

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
- `docs/demo-script.md`: a 60-second demo script and recording steps;
  `scripts/demo_check.py` checks everything is up; `scripts/load_demo.py`
  `--phase-seconds` sets how long each quiet/hammer phase lasts.
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
