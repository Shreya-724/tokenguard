# Load test results

- started: 2026-10-27T12:46:10
- platform: Windows-10-10.0.19045-SP0
- cpus: 4
- python: 3.11.4
- redis: 7.4.11
- locust: 2.47.0
- users: 50
- duration: 30s (+5s warmup)
- repeats: 3
- metrics: True
- live_rules: True

Latency in milliseconds, throughput in requests per second. Each row is the median of the repeats; `rps range` is the lowest and highest repeat. Locust rounds percentiles to whole milliseconds, so a difference under 1 ms shows up in `avg` and in req/s, not in p50/p95/p99.

## allowed

| mode | req/s | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 140 | 127-171 | 355.88 | 330 | 510 | 820 | 1096 | 0 | 12678 | - |
| limited | 118 | 91-122 | 419.45 | 410 | 570 | 820 | 1110 | 0 | 9630 | - |
| **overhead** | -15.3% | | +63.57 | +80 | +60 | +0 | | | | |

## blocked

| mode | req/s | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 164 | 118-180 | 302.24 | 290 | 530 | 730 | 946 | 0 | 13648 | - |
| limited | 94 | 84-109 | 528.01 | 510 | 730 | 1000 | 1132 | 0 | 15 | 8314 |
| **overhead** | -42.7% | | +225.77 | +220 | +200 | +270 | | | | |

## distinct

| mode | req/s | rps range | avg | p50 | p95 | p99 | max | fail | 200 | 429 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline | 121 | 119-133 | 404.89 | 380 | 600 | 780 | 989 | 0 | 10858 | - |
| limited | 87 | 83-88 | 569.38 | 540 | 770 | 990 | 1131 | 0 | 7491 | - |
| **overhead** | -27.9% | | +164.50 | +160 | +170 | +210 | | | | |
