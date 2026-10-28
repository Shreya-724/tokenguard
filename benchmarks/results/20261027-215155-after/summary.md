# Load test results

- started: 2026-10-27T21:51:55
- platform: Windows-10-10.0.19045-SP0
- cpus: 4
- python: 3.11.4
- redis: 7.4.11
- locust: 2.47.0
- users: 50
- duration: 30s (+5s warmup)
- repeats: 3
- metrics: True
- metrics_flush: 0.2
- live_rules: True

Latency in milliseconds, throughput in requests per second. Each row is the median of the repeats; `rps range` is the lowest and highest repeat. Locust rounds percentiles to whole milliseconds, so a difference under 1 ms shows up in `avg` and in req/s, not in p50/p95/p99. `ms/req` is 1000 / req/s: the server time one request costs when the server is saturated. Under load, latency is mostly queueing, so compare `ms/req`, not p50.

## allowed

| mode | req/s | ms/req | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 350 | 2.86 | 343-378 | 142.06 | 130 | 210 | 300 | 373 | 0 | 31606 | - |
| limited | 285 | 3.51 | 278-294 | 174.29 | 160 | 260 | 330 | 430 | 0 | 25387 | - |
| **overhead** | -18.5% | +0.65 | | +32.23 | +30 | +50 | +30 | | | | |

## blocked

| mode | req/s | ms/req | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 368 | 2.72 | 349-381 | 135.13 | 120 | 210 | 290 | 365 | 0 | 32457 | - |
| limited | 269 | 3.72 | 238-269 | 184.88 | 170 | 280 | 340 | 507 | 0 | 15 | 22908 |
| **overhead** | -26.9% | +1.00 | | +49.75 | +50 | +70 | +50 | | | | |

## distinct

| mode | req/s | ms/req | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 361 | 2.77 | 351-367 | 137.66 | 120 | 210 | 290 | 402 | 0 | 31698 | - |
| limited | 268 | 3.73 | 246-282 | 185.22 | 160 | 290 | 360 | 464 | 0 | 23396 | - |
| **overhead** | -25.7% | +0.96 | | +47.56 | +40 | +80 | +70 | | | | |
