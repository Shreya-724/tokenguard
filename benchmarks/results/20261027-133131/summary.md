# Load test results

- started: 2026-10-27T13:31:31
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
| baseline | 259 | 259-259 | 191.39 | 170 | 300 | 340 | 361 | 0 | 2375 | - |
| limited | 154 | 154-154 | 321.99 | 280 | 530 | 950 | 1004 | 0 | 1426 | - |
| **overhead** | -40.5% | | +130.60 | +110 | +230 | +610 | | | | |
