# Load test results

- started: 2026-10-27T21:38:53
- platform: Windows-10-10.0.19045-SP0
- cpus: 4
- python: 3.11.4
- redis: 7.4.11
- locust: 2.47.0
- users: 50
- duration: 30s (+5s warmup)
- repeats: 3
- metrics: True
- metrics_flush: 0.0
- live_rules: True

Latency in milliseconds, throughput in requests per second. Each row is the median of the repeats; `rps range` is the lowest and highest repeat. Locust rounds percentiles to whole milliseconds, so a difference under 1 ms shows up in `avg` and in req/s, not in p50/p95/p99. `ms/req` is 1000 / req/s: the server time one request costs when the server is saturated. Under load, latency is mostly queueing, so compare `ms/req`, not p50.

## allowed

| mode | req/s | ms/req | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 189 | 5.28 | 164-403 | 262.72 | 280 | 400 | 520 | 716 | 0 | 22298 | - |
| limited | 107 | 9.31 | 107-279 | 461.12 | 400 | 590 | 790 | 1062 | 0 | 14492 | - |
| **overhead** | -43.3% | +4.03 | | +198.40 | +120 | +190 | +270 | | | | |

## blocked

| mode | req/s | ms/req | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 353 | 2.84 | 147-409 | 141.23 | 120 | 230 | 600 | 794 | 0 | 26663 | - |
| limited | 244 | 4.10 | 98-250 | 203.11 | 180 | 320 | 420 | 496 | 0 | 15 | 17445 |
| **overhead** | -30.8% | +1.26 | | +61.88 | +60 | +90 | -180 | | | | |

## distinct

| mode | req/s | ms/req | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 334 | 3.00 | 100-403 | 148.79 | 120 | 250 | 510 | 1149 | 0 | 24648 | - |
| limited | 233 | 4.28 | 165-279 | 213.05 | 200 | 330 | 380 | 451 | 0 | 19925 | - |
| **overhead** | -30.1% | +1.29 | | +64.26 | +80 | +80 | -130 | | | | |
