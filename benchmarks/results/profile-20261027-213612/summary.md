# Where one decision spends its time (no web server)

- started: 2026-10-27 21:36:40, 3000 calls per case
- redis: redis://127.0.0.1:6379/5

Microseconds per call. `in Redis` is time waiting on Redis round trips (network included); `in Python` is the rest.

| case | round trips/call | total | in Redis | in Python | vs check only |
|---|---:|---:|---:|---:|---:|
| check only | 1.00 | 1111 | 1021 | 90 | +0 |
| check + metrics | 2.00 | 1700 | 1590 | 111 | +589 |
| check + buffered (0.2s) | 1.01 | 1496 | 1375 | 120 | +384 |
