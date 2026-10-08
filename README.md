![CI](https://github.com/<Shreya-724>/tokenguard/actions/workflows/ci.yml/badge.svg)
# tokenguard
A token-aware, Redis-backed rate limiter for Django, built for LLM APIs.

**Goal:** limit requests by *tokens consumed*, not just request count, with
atomic correctness under concurrency and a live dashboard.

**Status:** Week 1 of 8, in-memory core algorithm.

## How a token bucket works
A bucket holds up to `capacity` tokens and refills at `refill_rate` per second.
Each request spends tokens. If the bucket has enough, it's allowed; otherwise
it's rejected with a `retry_after`.

Example: capacity=10, refill=1/sec
- t=0:  10 tokens. 10 requests arrive together → all allowed, 0 left
- t=0:  11th request → rejected, retry_after = 1.0s
- t=3:  3 tokens refilled → a cost-3 request is allowed
- t=1h: bucket is back to 10, never more (capped at capacity)

Bursts are allowed up to `capacity`, while the long-run average is limited
to `refill_rate`.