# Algorithm benchmarks

- measured: 2026-10-28 13:35
- machine: Windows-10-10.0.19045-SP0, Python 3.11.4
- redis: 7.4.11, 2000 calls per case

## Memory per key (bytes, Redis MEMORY USAGE)

A key whose limit is used up. The token bucket and the fixed window are one fixed-size value; the sliding window keeps one entry per request.

| algorithm | after 1 request | limit 10 full | limit 100 full | limit 1k full | limit 10k full |
|---|---:|---:|---:|---:|---:|
| token_bucket | 120 | 128 | 120 | 128 | 128 |
| fixed_window | 112 | 112 | 112 | 120 | 120 |
| sliding_window | 144 | 728 | 6,232 | 116,224 | 1,269,440 |

## Latency per check() call (microseconds, network included)

| algorithm | case | calls | p50 | p95 | p99 | max |
|---|---|---:|---:|---:|---:|---:|
| token_bucket | new key | 2000 | 915 | 1327 | 1802 | 3752 |
| token_bucket | full key, limit 10 | 2000 | 1165 | 1962 | 2957 | 20313 |
| token_bucket | full key, limit 100 | 2000 | 1801 | 2127 | 2438 | 5657 |
| token_bucket | full key, limit 1k | 2000 | 865 | 2062 | 2803 | 28927 |
| token_bucket | full key, limit 10k | 2000 | 887 | 1318 | 1660 | 4240 |
| fixed_window | new key | 2000 | 828 | 1109 | 1626 | 3843 |
| fixed_window | full key, limit 10 | 2000 | 843 | 1035 | 1177 | 2660 |
| fixed_window | full key, limit 100 | 2000 | 1737 | 1999 | 2187 | 3050 |
| fixed_window | full key, limit 1k | 2000 | 1289 | 1939 | 2739 | 6023 |
| fixed_window | full key, limit 10k | 2000 | 821 | 1053 | 1339 | 4096 |
| sliding_window | new key | 2000 | 1344 | 1936 | 2657 | 5776 |
| sliding_window | full key, limit 10 | 2000 | 1493 | 2078 | 2279 | 5617 |
| sliding_window | full key, limit 100 | 2000 | 1324 | 2635 | 3559 | 7727 |
| sliding_window | full key, limit 1k | 2000 | 3234 | 5686 | 6176 | 13335 |
| sliding_window | full key, limit 10k | 2000 | 21516 | 40527 | 50561 | 114506 |
