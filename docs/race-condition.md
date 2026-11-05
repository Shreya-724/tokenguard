# The check-then-act race, reproduced and fixed

A rate limiter has one job: never allow more than the limit. This page shows the
obvious Redis implementation breaking that promise under concurrency, and the fix.

## The bug

The first Redis version (`NaiveRedisTokenBucket`, kept in the package on purpose)
did what the in-memory bucket did, with Redis as the storage:

```python
tokens, ts = redis.hmget(key, "tokens", "ts")  # 1. READ
tokens = min(capacity, tokens + elapsed * rate)  # 2. COMPUTE, in Python
if tokens >= cost:
    tokens -= cost
    redis.hset(key, mapping={"tokens": tokens})  # 3. WRITE
```

Each line is correct. The sequence is not, because other clients run between the
lines. With one token left:

| Time | Client A | Client B | Tokens in Redis |
|---|---|---|---|
| 1 | READ: 1 token | | 1 |
| 2 | | READ: 1 token | 1 |
| 3 | COMPUTE: allowed, 0 left | | 1 |
| 4 | | COMPUTE: allowed, 0 left | 1 |
| 5 | WRITE: 0 | | 0 |
| 6 | | WRITE: 0 | 0 |

Both were told "allowed", but only one token existed. This is a *check-then-act*
race: the check (is there a token?) and the act (spend it) are not one step. It
never shows up with one client, and it needs no unusual timing, only two requests in
flight at once, which is what a busy server is.

## The reproduction

```bash
python scripts/race_demo.py --redis redis://127.0.0.1:6379/5
```

Several processes, each with its own connection, start together (a barrier) and spend
from **one** bucket that holds 100 tokens and refills too slowly to matter. A correct
limiter allows exactly 100.

Result of one run (8 processes x 50 attempts = 400 requests, 5 rounds, Redis 7.0 on
localhost, a 2-core Linux container):

| Implementation | Allowed per round (min..max) | Rounds over the limit | Worst case |
|---|---|---|---|
| naive (read, compute, write) | 318..354 | 5 of 5 | 254 too many |
| token bucket (Lua) | 100..100 | 0 of 5 | exact |
| fixed window (Lua) | 100..100 | 0 of 5 | exact |
| sliding window (Lua) | 100..100 | 0 of 5 | exact |

The naive limiter let through about three times the limit. Your numbers will differ
with your machine, Redis and process count (more processes and a faster network make
the race worse), so run the script and use your own. The Lua rows should always
read exactly the limit; the script exits with status 1 if they do not.

The same property is a test that runs in CI:
`tests/test_algorithms_concurrency.py` (8 processes, 400 attempts, limit 100,
asserts exactly 100 for every algorithm).

## The fix

Move the read, the compute and the write into one Lua script. Redis runs a script as
a single command: no other client's command runs in the middle of it.

```lua
local data = redis.call('HMGET', KEYS[1], 'tokens', 'ts')   -- read
-- ... refill, decide ...                                     -- compute
redis.call('HSET', KEYS[1], 'tokens', tokens, 'ts', now)    -- write
```

Three more things the script settles:

- **One round trip** instead of three, so it is faster as well as correct.
- **The clock is Redis's `TIME`**, read inside the script. Two app servers whose
  clocks differ by a second would otherwise refill the same bucket by different
  amounts.
- **Every algorithm does this**, including budgets (burst, daily and monthly counters
  are checked and charged in one script, so a refused request leaves no trace).

## Costs of the fix

- A script runs to completion while everything else in that Redis waits. These are a
  handful of hash operations (the sliding window is the exception: its cost grows with
  the log, see [algorithm-benchmarks.md](algorithm-benchmarks.md)).
- The logic is in a second language, which is harder to step through and test.
  `tests/` runs the scripts against a real Redis for that reason.
- On Redis Cluster every key a script touches must live in the same slot, so keys that
  belong together share a hash tag.

## What a test can and cannot prove

The test demonstrates the race on the naive version (it allows more than the limit)
and the absence of it on the Lua version (exactly the limit, in every round). It
cannot prove the Lua version is correct for all interleavings; the argument for that
is that Redis executes the script atomically, so there are no interleavings inside it.
