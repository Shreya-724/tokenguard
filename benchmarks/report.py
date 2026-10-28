"""Turn raw Locust output into numbers and a Markdown table. No dependencies.

    python benchmarks/report.py benchmarks/results/<run-id>

Reads <run-id>/raw/<mode>_<scenario>_r<N>_stats.csv (and _status.json) and
writes <run-id>/summary.json and <run-id>/summary.md. run_bench.py calls this
at the end of a run; call it yourself to rebuild a summary from raw files.

The median of the repeats is reported, not the best: a best-of-N number is
the kind a reviewer is right to distrust.
"""

import csv
import json
import re
import statistics
import sys
from pathlib import Path

RAW_NAME = re.compile(
    r"^(?P<mode>[a-z]+)_(?P<scenario>[a-z]+)_r(?P<repeat>\d+)_stats\.csv$"
)
METRICS = ("rps", "avg", "p50", "p95", "p99", "max")


def parse_stats(path):
    """The 'Aggregated' row of a Locust *_stats.csv, with plain names."""
    with open(path, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["Name"] == "Aggregated":
                return {
                    "requests": int(row["Request Count"]),
                    "failures": int(row["Failure Count"]),
                    "rps": float(row["Requests/s"]),
                    "avg": float(row["Average Response Time"]),
                    "p50": float(row["50%"]),
                    "p95": float(row["95%"]),
                    "p99": float(row["99%"]),
                    "max": float(row["Max Response Time"]),
                }
    raise ValueError(f"no Aggregated row in {path}")


def combine(runs):
    """One result from several repeats: medians, summed counts."""
    out = {key: statistics.median(run[key] for run in runs) for key in METRICS}
    out["ms_per_req"] = 1000 / out["rps"] if out["rps"] else 0.0
    out["requests"] = sum(run["requests"] for run in runs)
    out["failures"] = sum(run["failures"] for run in runs)
    out["repeats"] = len(runs)
    out["rps_min"] = min(run["rps"] for run in runs)
    out["rps_max"] = max(run["rps"] for run in runs)
    return out


def overhead(base, limited):
    """What the limiter added. Latency in ms; throughput as a % change."""
    return {
        "rps_change_pct": (limited["rps"] - base["rps"]) / base["rps"] * 100,
        "p50_ms": limited["p50"] - base["p50"],
        "p95_ms": limited["p95"] - base["p95"],
        "p99_ms": limited["p99"] - base["p99"],
        "avg_ms": limited["avg"] - base["avg"],
        "ms_per_req": limited["ms_per_req"] - base["ms_per_req"],
    }


def collect(run_dir):
    """{scenario: {mode: combined result + status counts}} from raw/ files."""
    raw = Path(run_dir) / "raw"
    runs = {}
    for path in sorted(raw.glob("*_stats.csv")):
        match = RAW_NAME.match(path.name)
        if not match:
            continue
        runs.setdefault((match["scenario"], match["mode"]), []).append(
            (int(match["repeat"]), path)
        )
    results = {}
    for (scenario, mode), files in runs.items():
        stats = [parse_stats(path) for _, path in sorted(files)]
        combined = combine(stats)
        codes = {}
        for _, path in files:
            status = path.with_name(path.name.replace("_stats.csv", "_status.json"))
            if status.exists():
                for code, n in json.loads(status.read_text()).items():
                    codes[code] = codes.get(code, 0) + n
        combined["status"] = codes
        results.setdefault(scenario, {})[mode] = combined
    for modes in results.values():
        if "baseline" in modes and "limited" in modes:
            modes["overhead"] = overhead(modes["baseline"], modes["limited"])
    return results


def render_markdown(results, meta=None):
    lines = ["# Load test results", ""]
    if meta:
        keys = ("started", "platform", "cpus", "python", "redis", "locust")
        lines += [f"- {k}: {meta[k]}" for k in keys if k in meta]
        for key in (
            "users",
            "duration",
            "repeats",
            "metrics",
            "metrics_flush",
            "live_rules",
        ):
            if key in meta:
                lines.append(f"- {key}: {meta[key]}")
        lines.append("")
    lines += [
        "Latency in milliseconds, throughput in requests per second. Each row is "
        "the median of the repeats; `rps range` is the lowest and highest repeat. "
        "Locust rounds percentiles to whole milliseconds, so a difference under "
        "1 ms shows up in `avg` and in req/s, not in p50/p95/p99. `ms/req` is "
        "1000 / req/s: the server time one request costs when the server is "
        "saturated. Under load, latency is mostly queueing, so compare `ms/req`, "
        "not p50.",
        "",
    ]
    for scenario in sorted(results):
        lines += [f"## {scenario}", ""]
        lines.append(
            "| mode | req/s | ms/req | rps range | avg | p50 | p95 | p99 | max "
            "| fail | 200 | 429 |"
        )
        lines.append("|---|" + "---:|" * 11)
        for mode in ("baseline", "limited"):
            r = results[scenario].get(mode)
            if not r:
                continue
            st = r.get("status", {})
            lines.append(
                f"| {mode} | {r['rps']:.0f} | {r['ms_per_req']:.2f} "
                f"| {r['rps_min']:.0f}-{r['rps_max']:.0f} "
                f"| {r['avg']:.2f} | {r['p50']:.0f} | {r['p95']:.0f} "
                f"| {r['p99']:.0f} | {r['max']:.0f} "
                f"| {r['failures']} | {st.get('200', '-')} | {st.get('429', '-')} |"
            )
        extra = results[scenario].get("overhead")
        if extra:
            lines.append(
                f"| **overhead** | {extra['rps_change_pct']:+.1f}% "
                f"| {extra['ms_per_req']:+.2f} | | "
                f"{extra['avg_ms']:+.2f} | {extra['p50_ms']:+.0f} "
                f"| {extra['p95_ms']:+.0f} | {extra['p99_ms']:+.0f} | | | | |"
            )
        lines.append("")
    return "\n".join(lines)


def write(run_dir):
    run_dir = Path(run_dir)
    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else None
    results = collect(run_dir)
    (run_dir / "summary.json").write_text(json.dumps(results, indent=2))
    (run_dir / "summary.md").write_text(render_markdown(results, meta))
    return results


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    write(sys.argv[1])
    print((Path(sys.argv[1]) / "summary.md").read_text())
