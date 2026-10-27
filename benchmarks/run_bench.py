"""Run the load test: baseline (no limiter) vs limited, every scenario.

    python benchmarks/run_bench.py                      # the full matrix
    python benchmarks/run_bench.py --duration 10 --repeats 1 --scenarios allowed

Needs: Redis running, and `pip install -e ".[dev]" locust`. For each repeat,
scenario and mode it starts a fresh server, warms it up, empties the throwaway
Redis database, runs Locust, and saves the raw CSVs under
benchmarks/results/<run-id>/raw/. Then it writes summary.md and summary.json.

The server and the load generator share your machine and compete for CPU, so
the absolute numbers belong to this machine. The difference between baseline
and limited is the thing to quote, and only with the machine described.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import redis

ROOT = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent
SCENARIOS = {
    "allowed": "AllowedUser",
    "blocked": "BlockedUser",
    "distinct": "DistinctUser",
}
sys.path.insert(0, str(HERE))
import report  # noqa: E402


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--users", type=int, default=50, help="concurrent users")
    parser.add_argument("--duration", type=int, default=30, help="seconds per run")
    parser.add_argument("--warmup", type=int, default=5, help="seconds, not recorded")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--scenarios", default=",".join(SCENARIOS))
    parser.add_argument("--modes", default="baseline,limited")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--redis",
        default="redis://localhost:6379/5",
        help="a THROWAWAY database: it is emptied before every run",
    )
    parser.add_argument(
        "--metrics", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--live-rules", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--label", default="", help="added to the run folder name")
    return parser.parse_args(argv)


def check_redis(url):
    """Refuse to empty database 0 by accident."""
    db = urlparse(url).path.strip("/") or "0"
    if db == "0":
        sys.exit("--redis must use a non-zero database (it gets flushed): /5")
    client = redis.Redis.from_url(url)
    client.ping()
    return client


def wait_for(url, expect, timeout=30):
    """Poll /bench/mode/ until the server answers; return what it says."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                info = json.load(response)
            if info["mode"] != expect:
                raise RuntimeError(f"server runs {info['mode']!r}, wanted {expect!r}")
            return info
        except (OSError, ValueError):
            time.sleep(0.25)
    raise RuntimeError(f"server did not come up at {url}")


def start_server(args, mode):
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "demo_site.bench_settings",
        "PYTHONPATH": os.pathsep.join([str(ROOT / "demo"), str(ROOT / "src")]),
        "BENCH_MODE": mode,
        "BENCH_REDIS_URL": args.redis,
        "BENCH_METRICS": "1" if args.metrics else "0",
        "BENCH_LIVE_RULES": "1" if args.live_rules else "0",
    }
    cmd = [
        sys.executable, "-m", "daphne", "-v", "0",
        "-b", "127.0.0.1", "-p", str(args.port), "demo_site.asgi:application",
    ]  # fmt: skip
    return subprocess.Popen(cmd, cwd=ROOT, env=env)


def locust(args, scenario, seconds, csv_prefix=None, status_file=None):
    cmd = [
        sys.executable, "-m", "locust", "-f", str(HERE / "locustfile.py"),
        "--headless", "--only-summary", "--host", f"http://127.0.0.1:{args.port}",
        "-u", str(args.users), "-r", str(args.users), "-t", f"{seconds}s",
    ]  # fmt: skip
    if csv_prefix:
        cmd += ["--csv", str(csv_prefix)]
    cmd.append(SCENARIOS[scenario])
    env = {**os.environ}
    if status_file:
        env["BENCH_STATUS_FILE"] = str(status_file)
    subprocess.run(cmd, cwd=ROOT, env=env, check=False)  # exit 1 = some failures


def one_run(args, client, raw, mode, scenario, repeat):
    url = f"http://127.0.0.1:{args.port}/bench/mode/"
    server = start_server(args, mode)
    try:
        wait_for(url, mode)
        if args.warmup:
            locust(args, scenario, args.warmup)
        client.flushdb()
        stem = f"{mode}_{scenario}_r{repeat}"
        locust(args, scenario, args.duration, raw / stem, raw / f"{stem}_status.json")
        info = {
            "keys": client.dbsize(),
            "used_memory": client.info("memory")["used_memory"],
        }
        (raw / f"{stem}_redis.json").write_text(json.dumps(info))
    finally:
        server.terminate()
        server.wait(timeout=15)


def main(argv=None):
    args = parse_args(argv)
    client = check_redis(args.redis)
    scenarios = [s for s in args.scenarios.split(",") if s]
    modes = [m for m in args.modes.split(",") if m]
    for name in scenarios:
        if name not in SCENARIOS:
            sys.exit(f"unknown scenario {name!r}; choose from {', '.join(SCENARIOS)}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = HERE / "results" / (stamp + (f"-{args.label}" if args.label else ""))
    raw = run_dir / "raw"
    raw.mkdir(parents=True)
    try:
        from importlib.metadata import version

        locust_version = version("locust")
    except Exception:
        locust_version = "unknown"
    meta = {
        "started": datetime.now().isoformat(timespec="seconds"),
        "platform": platform.platform(),
        "cpus": os.cpu_count(),
        "python": platform.python_version(),
        "redis": client.info("server")["redis_version"],
        "locust": locust_version,
        "users": args.users,
        "duration": f"{args.duration}s (+{args.warmup}s warmup)",
        "repeats": args.repeats,
        "metrics": args.metrics,
        "live_rules": args.live_rules,
        "label": args.label,
    }
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2))
    for repeat in range(1, args.repeats + 1):
        for scenario in scenarios:
            for mode in modes:  # alternate modes so slow drift hits both
                print(f"\n=== repeat {repeat}: {scenario} / {mode} ===", flush=True)
                one_run(args, client, raw, mode, scenario, repeat)
    report.write(run_dir)
    print(f"\nSaved {run_dir}\n")
    print((run_dir / "summary.md").read_text())


if __name__ == "__main__":
    main()
