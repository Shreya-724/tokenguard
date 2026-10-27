# Limiter latency (no web server)

- started: 2026-10-27 13:00:34
- platform: Windows-10-10.0.19045-SP0, Python 3.11.4
- redis: 7.4.11, 5000 calls per case

Microseconds per call. `p50 over PING` is the median minus the median of a bare PING: the limiter's own cost.

| case | mean | p50 | p95 | p99 | max | p50 over PING |
|---|---:|---:|---:|---:|---:|---:|
| redis PING | 881 | 643 | 1869 | 3085 | 8599 | +0 |
| token_bucket | 1273 | 961 | 2821 | 4757 | 15692 | +317 |
| token_bucket+metrics | 2964 | 2615 | 6045 | 7684 | 20814 | +1972 |
| token_bucket/new key | 1359 | 1009 | 3245 | 5226 | 15781 | +365 |
| fixed_window | 1632 | 1209 | 4706 | 5744 | 15085 | +566 |
| sliding_window | 2906 | 2304 | 6365 | 10182 | 27168 | +1660 |
