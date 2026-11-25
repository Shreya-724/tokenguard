# Design and limits

How tokenguard works inside, why it is built this way, and where it stops.
For the short version, see the [README](../README.md).

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

400 requests from 8 processes at once, against a bucket that holds 100 (5 rounds, Redis 7
on localhost):

| Implementation | Allowed per round | Over the limit |
|---|---|---|
| Naive (read, compute, write) | 318 to 354 | 5 of 5 rounds |
| Atomic Lua script (all three algorithms) | exactly 100 | 0 of 5 rounds |

Reproduce it, and get numbers for your own machine: `python scripts/race_demo.py`.

The fix moves the whole read-compute-write into one Lua script, which Redis executes
atomically. See [docs/race-condition.md](race-condition.md) for the reproduction.

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
- Metrics cost one extra Redis call per limited request, unless
  `METRICS_FLUSH_INTERVAL` batches them (see Performance). Each
  minute keeps at most `METRICS_MAX_CONSUMERS` consumers per ranking, so a long tail
  of one-off keys may be missing from the top lists. Times come from the app server's
  clock.
- Dashboard: the "most blocked" panel is a ranking per key, not a log of requests;
  bucket levels are not available for budgeted rules; chart history lives in the
  browser tab; it needs the `tokenguard_feed` process running to update.
