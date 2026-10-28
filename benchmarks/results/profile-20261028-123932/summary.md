# Where one decision spends its time (no web server)

- started: 2026-10-28 12:39:54, 3000 calls per case
- redis: redis://127.0.0.1:6379/5

Microseconds per call. `in Redis` is time waiting on Redis round trips (network included); `in Python` is the rest.

| case | round trips/call | total | in Redis | in Python | vs check only |
|---|---:|---:|---:|---:|---:|
| check only | 1.00 | 1648 | 1514 | 133 | +0 |
| check + metrics | 2.00 | 1998 | 1869 | 129 | +351 |
| check + buffered (0.2s) | 1.00 | 994 | 902 | 92 | -654 |
