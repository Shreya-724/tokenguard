# The race condition (naive Redis token bucket)

Setup: capacity 100, 1,000 requests, refill ≈ 0 (0.0001 tokens/s), local Redis 7
in Docker. A correct limiter must allow exactly 100.

| Run | Mode | Allowed | Over limit by |
|-----|------|--------:|--------------:|
| 1 | 50 threads | 566 | 466 |
| 2 | 50 threads | 1000 | 900 |
| 3 | 50 threads | 577 | 477 |
| 4 | 50 threads | 1000 | 900 |
| 5 | 8 processes | 199 | 99 |
| 6 | 8 processes | 161 | 61 |
| 7 | 8 processes | 261 | 161 |

Across 7 runs the naive limiter admitted 1.6x to 10x its limit. In two runs it
allowed every request.

## Why
The naive limiter does read, compute, write as three separate steps. Many
requests can read the same token count before any of them writes back, so each
computes "tokens left" from stale data and writes it, overwriting the others'
spends. The result varies run to run because it depends on timing. This is a
check-then-act race: checking for tokens and spending them are not atomic. More
concurrency makes it worse, which is why threads (more requests in flight) are
worse than processes.