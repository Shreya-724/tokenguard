# Benchmarks

Baseline latency measurements for each implementation.

**Setup:** Redis running on localhost, same machine as the benchmark client (Windows, Python 3.11.4). Numbers include no real network hop, so expect higher latencies against a remote Redis.

## Latency per check

| Implementation | p50 | p95 | p99 |
|----------------|-----|-----|-----|
| In-memory | 0.002 ms | 0.002 ms | 0.003 ms |
| Naive (read, compute, write) | 1.847 ms | 3.086 ms | 4.240 ms |
| Atomic Lua script | 0.510 ms | 1.132 ms | 2.110 ms |

## Takeaways

- The Lua script is about 3.6x faster than the naive version at p50 (0.510 ms vs 1.847 ms), and about 2x faster at p99. The naive version is also the one that fails the concurrency test, so the atomic version is both more correct and faster.
- A likely reason: the naive path needs multiple Redis round trips (read, then write), while the Lua script does everything in one.
- The in-memory implementation is roughly 250x faster than the Lua script at p50, but it is process-local and cannot enforce limits across processes or machines. The gap shows the cost of going through Redis.

## Reproduce

```bash
python scripts/latency.py
```

Raw output:

```
memory   p50=0.002ms  p95=0.002ms  p99=0.003ms
naive    p50=1.847ms  p95=3.086ms  p99=4.240ms
lua      p50=0.510ms  p95=1.132ms  p99=2.110ms
```

These are a single-machine baseline; rerun on your target environment before drawing conclusions about production latency.