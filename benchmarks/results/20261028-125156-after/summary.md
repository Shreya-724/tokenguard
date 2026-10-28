# Load test results

- started: 2026-10-28T12:51:56
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
| baseline | 369 | 2.71 | 363-386 | 134.67 | 110 | 220 | 310 | 411 | 0 | 32943 | - |
| limited | 278 | 3.60 | 278-300 | 179.06 | 160 | 280 | 340 | 434 | 0 | 25295 | - |
| **overhead** | -24.7% | +0.89 | | +44.38 | +50 | +60 | +30 | | | | |

## blocked

| mode | req/s | ms/req | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 391 | 2.56 | 380-392 | 127.10 | 110 | 200 | 270 | 432 | 0 | 34308 | - |
| limited | 270 | 3.70 | 256-283 | 184.02 | 160 | 280 | 380 | 487 | 0 | 15 | 23859 |
| **overhead** | -30.9% | +1.15 | | +56.92 | +50 | +80 | +110 | | | | |

## distinct

| mode | req/s | ms/req | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 375 | 2.67 | 367-394 | 132.38 | 120 | 200 | 300 | 452 | 0 | 33459 | - |
| limited | 294 | 3.40 | 293-297 | 169.07 | 150 | 250 | 320 | 424 | 0 | 26123 | - |
| **overhead** | -21.6% | +0.74 | | +36.69 | +30 | +50 | +20 | | | | |
