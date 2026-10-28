# Benchmarks

Two tools. Both write raw files you can commit, so every number in the README
can be traced back to a file.

| tool | measures | needs |
|---|---|---|
| `run_bench.py` | requests/s and latency of a real Django server, with and without the limiter | Redis, `pip install -e ".[bench]"` |
| `limiter_bench.py` | microseconds per `check()` call against Redis, no web server | Redis |

## Run the load test (Day 1 and 2)

```powershell
pip install -e ".[bench]"
docker compose up -d redis        # or your existing Docker Redis on 6379
python benchmarks/run_bench.py --duration 10 --repeats 1 --scenarios allowed   # quick check
python benchmarks/run_bench.py                                                  # the real run
```

The full run is 3 scenarios x 2 modes x 3 repeats x ~45 s, about 15 minutes.
Close other heavy programs first and leave the machine alone while it runs.

Each run starts a fresh server, warms it up for 5 s (not recorded), empties
Redis database 5 (it refuses database 0), then records 30 s. Modes alternate
inside each repeat so a slow drift hits both.

Output: `benchmarks/results/<timestamp>/`

- `raw/*_stats.csv` Locust's own numbers, untouched. These are the evidence.
- `raw/*_status.json` how many 200s and 429s came back.
- `raw/*_redis.json` keys and memory left in Redis after the run.
- `meta.json` machine, versions, users, duration.
- `summary.md` / `summary.json` medians and the overhead. Rebuild with
  `python benchmarks/report.py benchmarks/results/<timestamp>`.

## Scenarios

- `allowed`: 20 callers with limits too big to hit. The limiter says yes every time.
- `blocked`: 5 callers with 1 token and no refill. The limiter says no almost every time.
- `distinct`: a new caller on every request. Creates a Redis key per request.

`baseline` runs the identical views without the decorator
(`BENCH_MODE=baseline`). In `blocked` the baseline never returns 429, so it
does more work per request than the limited run; read that row knowing it.

## Reading the numbers honestly

- The server and Locust share one machine. Absolute requests/s is a property
  of that machine; the **difference** between baseline and limited is the result.
- Locust rounds percentiles to whole milliseconds. A cost below 1 ms shows in
  `avg` and in req/s, not in p50/p95/p99. `limiter_bench.py` gives the
  microsecond view.
- If the repeats disagree a lot (`rps range` is wide), the run is noisy. Re-run
  it before quoting anything.
- `--users` changes the answer: more users than the server can serve just
  queues, and latency becomes queue time. Quote the user count with the number.
- Write down your machine: CPU, RAM, Windows, Docker Redis (it runs in a VM,
  which adds latency compared with native Redis).

## Run the limiter-only benchmark

```powershell
python benchmarks/limiter_bench.py redis://localhost:6379/5
```

`sliding_window` is slow here because the log keeps one entry per allowed
request and the always-allowed limit never trims it. That is the algorithm's
real memory and time cost, shown on purpose, and Day 5 compares it properly.

## Find the bottleneck (Day 3)

```powershell
python benchmarks/profile_limiter.py redis://127.0.0.1:6379/5
```

It prints round trips per call and splits the time into "in Redis" and "in
Python" for: the check alone, the check plus the metrics write, and the check
plus buffered metrics. `profile.txt` (in the results folder) lists the most
expensive functions. Read it before deciding what to fix: the biggest number
is the one to attack, whatever you expected.

## Before and after (Day 4)

```powershell
python benchmarks/run_bench.py --label before
python benchmarks/run_bench.py --label after --metrics-flush 0.2
python benchmarks/compare.py benchmarks/results/<before-folder> benchmarks/results/<after-folder> --readme README.md
```

`compare.py` puts the table between the `bench:start` / `bench:end` markers in
the README and prints a warning if the baseline moved more than 10% between
the two runs (then the machine was not steady, so repeat). Run both with the
same `--users`, close the same programs, and do not touch the machine during
either.

Use `--users 5` as well as the default 50: at 50 the server is saturated, so
latency is mostly queueing; at 5 it is closer to the real cost of one request.

## Compare the algorithms (Day 5)

```powershell
python benchmarks/algo_bench.py redis://127.0.0.1:6379/5 --docs docs
```

Time per `check()` and Redis `MEMORY USAGE` per key for the token bucket, fixed
window and sliding window, on a brand new key and on a key whose limit is used
up, at limits of 10, 100, 1,000 and 10,000. It writes `docs/algorithm-benchmarks.md`
and its chart, and the raw CSVs under `results/algos-<time>/`.

For limits of 1,000 and above the sliding window is filled by writing its sorted
set directly, because filling it through `check()` is quadratic. A test confirms
the result is byte-for-byte the same size as real requests produce. Those cells
use at most 500 timed calls, because each call is slow; the table says how many.
