# Metrics

tokenguard can record every limiter decision, so you can ask what is happening:
how much traffic there is, how much of it is being blocked, and who is using the
most. This is what the dashboard (later this week) reads.

Turn it on:

```python
TOKENGUARD = {
    ...
    "METRICS": True,
    "METRICS_RETENTION": 3600,       # seconds of history kept (default)
    "METRICS_MAX_CONSUMERS": 1000,   # per minute, per ranking (default)
}
```

## What is recorded

For every request that reaches a rule:

| What | Detail |
|---|---|
| allowed / blocked | a 429 and a 413 both count as blocked |
| tokens | the cost units the rule charged (1 per request for a plain limit, model tokens for LLM routes); only allowed requests spend tokens |
| when | per second, so a chart can move once a second |
| which rule | per rule (`scope`), per minute |
| who | per consumer (`scope` + identity, such as `ip:10.0.0.1`), per minute |

LLM routes are corrected after the response: when `reconcile()` replaces the
estimate with real usage, or a failed request is refunded, the difference is
recorded, so token totals match what was really used.

Not recorded: requests that bypass the limiter (exempt paths), and decisions made
while Redis is down (there is nowhere to write them).

## How it is stored

All in Redis, nothing in process memory, so every worker sees the same numbers:

```
<prefix>:metrics:<minute>        hash:  <sec>:a  <sec>:b  <sec>:t      per second
                                        r:<scope>:a|b|t                per rule
<prefix>:metrics:top:<minute>    sorted set: consumer -> tokens spent
<prefix>:metrics:blk:<minute>    sorted set: consumer -> blocked requests
```

One Lua call per decision (one round trip, atomic), and every key expires after
`METRICS_RETENTION` seconds plus a small margin, so old data deletes itself.

**Cost.** It adds one Redis call to each limited request. Week 7 measures what
that costs; if it matters, the next step is folding it into the limiter's own
script. If Redis is slow or down, the sample is dropped and counted in
`recorder.dropped`; recording can never fail a request.

**Honest limits.**

- Each minute keeps at most `METRICS_MAX_CONSUMERS` consumers per ranking. When a
  ranking is full the smallest is dropped. Heavy users always survive; a long tail
  of one-off keys may be missing, which does not change a top-N list.
- Times come from the application server's clock, not Redis's. Keep servers on
  NTP.
- Top consumers and per-rule numbers are per whole minute, so a window of
  "5 minutes" is the current minute and the four before it.

## Asking questions

From a Django shell (`python manage.py shell`):

```python
from tokenguard.django.conf import get_metrics_reader

m = get_metrics_reader()

m.summary(60)  # requests, blocked ratio, requests/sec, tokens
m.timeseries(seconds=300)  # one Point per second; step=60 for per minute
m.top_consumers(n=5)  # who is using the most right now
m.top_consumers(by="blocked")  # who is turned away the most
m.routes()  # per-rule totals
m.bucket_level("chat", "user:42", Limit(60, 1))  # what this key has left
```

Without Django, build the reader yourself: `MetricsReader(redis_client, "tg:")`.
`bucket_level` only looks, it never spends, and works for every algorithm.

From a terminal, with the same Redis:

```
python scripts/tokenguard_stats.py stats
python scripts/tokenguard_stats.py top
python scripts/tokenguard_stats.py top --by blocked
python scripts/tokenguard_stats.py routes
python scripts/tokenguard_stats.py series --seconds 30
python scripts/tokenguard_stats.py bucket api ip:1.2.3.4 --capacity 60 --refill-rate 1
python scripts/tokenguard_stats.py watch
```

`python scripts/demo_metrics.py` shows all of it with simulated traffic and no
server.
