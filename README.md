![CI](https://github.com/<Shreya-724>/tokenguard/actions/workflows/ci.yml/badge.svg)
# tokenguard

A token-bucket rate limiter with an atomic Lua implementation, tested for correctness under heavy concurrency.

## Correctness under concurrency

1,000 requests, 50 threads / 8 processes, bucket capacity 100:

| Implementation | Mode | Allowed (expected 100) | Over limit by |
|----------------|------|------------------------|---------------|
| Naive (read, compute, write) | threads | **1000** | **900** |
| Atomic Lua script | threads | **exactly 100** | 0 |
| Atomic Lua script | processes | **exactly 100** | 0 |

The naive implementation reads the bucket, computes the new value, and writes it back as separate steps. Concurrent callers all read the same state before any of them writes, so every request is allowed and the limit is blown by 900. The Lua script runs the read, compute, and write as a single atomic operation on the server, so exactly `capacity` requests get through, every time.

## Test results

- `pytest tests/test_concurrency.py -v`: **25 passed** (20 thread runs + 5 process runs of the "exactly capacity allowed" test).
- Stress loop: the whole concurrency suite was run **20 times in a row** with no failures (25/25 passed each time, roughly 22 to 40 seconds per run). That is 500 test executions with zero flakes.

## Reproduce

```bash
# Run the concurrency tests
pytest tests/test_concurrency.py -v

# Race demos
python scripts/race_demo.py --impl lua --mode threads
python scripts/race_demo.py --impl lua --mode processes
python scripts/race_demo.py --impl naive --mode threads     # for contrast
```

Expected output:

```
impl=lua mode=threads capacity=100 requests=1000 allowed=100 over_limit_by=0
impl=lua mode=processes capacity=100 requests=1000 allowed=100 over_limit_by=0
impl=naive mode=threads capacity=100 requests=1000 allowed=1000 over_limit_by=900
```

To repeat the stress loop (PowerShell):

```powershell
for ($i=1; $i -le 20; $i++) { pytest -q tests/test_concurrency.py; if ($LASTEXITCODE -ne 0) { break } }
```

## Environment

Tested on Windows with Python 3.11.4 and pytest 9.1.1.