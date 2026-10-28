# Load test results

- started: 2026-10-28T12:39:55
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
| baseline | 354 | 2.82 | 292-377 | 140.32 | 120 | 220 | 290 | 449 | 0 | 30017 | - |
| limited | 227 | 4.41 | 200-263 | 219.25 | 210 | 350 | 410 | 436 | 0 | 20430 | - |
| **overhead** | -36.0% | +1.59 | | +78.93 | +90 | +130 | +120 | | | | |

## blocked

| mode | req/s | ms/req | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 377 | 2.65 | 324-388 | 131.90 | 120 | 210 | 270 | 435 | 0 | 32085 | - |
| limited | 218 | 4.59 | 216-249 | 227.38 | 210 | 320 | 410 | 544 | 0 | 15 | 20139 |
| **overhead** | -42.1% | +1.93 | | +95.48 | +90 | +110 | +140 | | | | |

## distinct

| mode | req/s | ms/req | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 374 | 2.67 | 258-385 | 132.65 | 120 | 210 | 280 | 496 | 0 | 29890 | - |
| limited | 240 | 4.17 | 153-265 | 206.62 | 190 | 330 | 450 | 745 | 0 | 19335 | - |
| **overhead** | -36.0% | +1.50 | | +73.98 | +70 | +120 | +170 | | | | |
