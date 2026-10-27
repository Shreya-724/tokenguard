# Load test results

- started: 2026-10-27T12:45:17
- platform: Windows-10-10.0.19045-SP0
- cpus: 4
- python: 3.11.4
- redis: 7.4.11
- locust: 2.47.0
- users: 50
- duration: 10s (+5s warmup)
- repeats: 1
- metrics: True
- live_rules: True

Latency in milliseconds, throughput in requests per second. Each row is the median of the repeats; `rps range` is the lowest and highest repeat. Locust rounds percentiles to whole milliseconds, so a difference under 1 ms shows up in `avg` and in req/s, not in p50/p95/p99.

## allowed

| mode | req/s | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 143 | 143-143 | 348.00 | 300 | 560 | 820 | 941 | 0 | 1306 | - |
| limited | 116 | 116-116 | 428.47 | 410 | 640 | 780 | 870 | 0 | 1067 | - |
| **overhead** | -18.8% | | +80.47 | +110 | +80 | -40 | | | | |
