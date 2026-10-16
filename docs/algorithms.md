# Algorithms

tokenguard can enforce a limit in more than one way. They all sit behind one
interface, so you pick one by name and nothing else in your code changes.

```python
from tokenguard.algorithms import Limit, get_algorithm

algorithm = get_algorithm("sliding_window", redis_client)
rule = Limit(capacity=60, refill_rate=1)
decision = algorithm.check("user:42", cost=1, rule=rule)
decision.allowed, decision.remaining, decision.retry_after
```

| Method | Meaning |
|---|---|
| `check(key, cost, rule) -> Decision` | Spend `cost` if it fits, and say whether it did |
| `peek(key, cost, rule) -> Decision` | The same answer, without spending |
| `adjust(key, delta, rule) -> float` | Settle an estimate: charge (`delta > 0`) or refund (`delta < 0`) |

## One rule, two numbers

`Limit(capacity, refill_rate)` means the same for every algorithm: `capacity` is
the most that can be spent at once, and `refill_rate` the sustained units per
second. Window algorithms read it as "`capacity` units per `capacity / refill_rate`
seconds", so `capacity=60, refill_rate=1` is 60 per minute and `capacity=60,
refill_rate=2` is 60 per 30 seconds. Switching algorithm keeps the long-run
average the same.

## Choosing one

```python
TOKENGUARD = {
    "ALGORITHM": "token_bucket",  # the default for every rule
    "RULES": [
        {
            "name": "login",
            "match": r"^/login/",
            "capacity": 5,
            "refill_rate": 0.1,
            "algorithm": "sliding_window",
        },  # this route only
    ],
}


@rate_limit(capacity=100, refill_rate=1, algorithm="fixed_window")  # this view only
def search(request): ...
```

Precedence: the view's or rule's `algorithm`, then the `ALGORITHM` setting, then
`token_bucket`. An unknown name is an error (`ImproperlyConfigured` for the
setting, `ValueError` for a rule or decorator).

## Comparison

| | Token bucket | Fixed window | Sliding window (log) |
|---|---|---|---|
| **How it counts** | A balance that refills smoothly | A counter reset at each window edge | The costs of the requests in the last `window` seconds |
| **Most in any window-length span** | 2 x capacity (a full burst, plus a window of refill) | 2 x capacity (across an edge) | 1 x capacity, exactly |
| **Burst behavior** | Up to `capacity` at once, then the refill rate | Up to `capacity` at once, again after each edge | Up to `capacity` at once, then only as old requests expire |
| **`retry_after`** | Exact | Exact (the window end) | Exact (when enough has expired) |
| **Memory per key** | 120 bytes | 120 bytes | ~540 bytes at a limit of 10, ~130 KB at a limit of 1,000 (about 130 bytes per request) |
| **Time per check** | O(1) | O(1) | O(requests in the window) |
| **Redis state** | A hash (`tokens`, `ts`) | A hash (`count`, `idx`) | A sorted set, one entry per request |
| **Works with budgets** | Yes (it is the burst layer) | No | No |

Memory is Redis `MEMORY USAGE` on Redis 7.0.15; reproduce all of it, including
timings on your own machine, with `python scripts/compare_algorithms.py`. In that
run (limit 100 full) a sliding-window check took roughly three times as long as the
other two, and that grows with the number of requests in the window.

The numbers hide one thing: a token bucket and a fixed window both allow up to twice
the capacity across a window-length span, for different reasons. The token bucket
lets a full bucket go at once and then keeps refilling. The fixed window forgets
everything at the edge. If "no more than N in any N-second span" is a hard
requirement, only the sliding window gives it.

## Which one should I use?

- **Default to the token bucket.** It is the cheapest in memory, handles bursts on
  purpose, and is the only one that works with budgets and with LLM token costs that
  are settled afterwards.
- **Use a fixed window** when you want the simplest thing to explain ("100 per
  minute, resets on the minute"), the limit is soft, and a short double burst at the
  edge is acceptable. It also reports a natural reset time.
- **Use the sliding window** when the limit is a hard promise (a contract, a paid
  quota, a login-attempt limit) and you must never exceed N in any span, **and** the
  limit is small: tens of requests per key, not thousands. Its memory and time grow
  with the requests in the window.

### The boundary problem (fixed window)

With 10 per 10 seconds:

```
t = 9.9s   10 requests  -> all allowed (the window is full)
t = 10.0s  10 requests  -> all allowed (a new window, counter reset)
```

That is 20 requests in 0.1 seconds. A token bucket with the same numbers refills
0.1 token in that time and a sliding window still remembers the first ten, so both
allow none. Each of these is a test (`tests/test_fixed_window.py`,
`tests/test_sliding_window.py`), and `tests/test_sliding_window.py` also runs an
attacker who hammers both sides of every edge: the fixed window lets 20 through in
a 10-second span, the sliding window never more than 10.

### Why a log, and not the cheaper sliding-window counter

The counter variant keeps two numbers (this window and the last) and estimates the
sliding total by weighting the last window, assuming its traffic was spread evenly.
It is cheap and stops the simple edge burst, but a burst packed at the very end of
one window, followed by another just before the end of the next, can still slip
through almost double. The log has no such gap, and a request costing 5,000 tokens is
still one entry. LLM traffic is a few expensive requests per key, which is where the
log's cost is lowest.

## Things to know

- **Budgets use the token bucket.** The burst layer of a budget is always a token
  bucket, so `budget=...` cannot be combined with `algorithm="fixed_window"` or
  `"sliding_window"` on the same rule (it raises `ValueError`).
- **`adjust` (settling an estimate).** A fixed window applies it to the current
  window, within `0` to `2 x capacity`; a refund that arrives after the window rolled
  over cannot be traced back to the old one. A sliding window shrinks the newest
  entries first on a refund and grows the newest entry on an extra charge, within the
  same bounds.
- **Keys.** A token bucket stores `<prefix>:<scope>:<identity>` (unchanged from
  before); a fixed window `<prefix>:fw:...`; a sliding window `<prefix>:sw:...`. So
  changing a rule's algorithm never reads another one's state.
- **Concurrency.** Every algorithm decides in one Lua script, so the count is exact
  under threads and processes: `tests/test_algorithms.py` and
  `tests/test_algorithms_concurrency.py` run the same check against all of them.

## Adding an algorithm

Implement `check`, `peek` and `adjust`, and register a factory:

```python
from tokenguard.algorithms import register_algorithm

register_algorithm(
    "my_algorithm", lambda client, clock=None, key_prefix="tb:": MyAlgorithm(...)
)
```

Then it is picked up by the contract tests in `tests/test_algorithms.py` (add its
name to `NAMES`) and `tests/test_algorithms_concurrency.py` (automatic): it has to
pass the same checks as the others (limits, costs, peek, retry hints, refunds, and
an exact count under concurrency).
