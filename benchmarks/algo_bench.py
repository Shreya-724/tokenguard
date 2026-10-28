"""Token bucket vs fixed window vs sliding window: speed and memory (Week 7, Day 5).

    python benchmarks/algo_bench.py [redis://127.0.0.1:6379/5] [--calls 2000]
    python benchmarks/algo_bench.py --docs docs   # also write docs/ page + chart

For each algorithm it measures, with no web server in the way:

    latency   microseconds per check() call (network round trip included) on
              a brand new key, and on a key whose limit is FULL, for limits of
              10, 100, 1,000 and 10,000. A full sliding-window key is its
              worst case: it holds one entry per request in the window.
    memory    Redis MEMORY USAGE of one key after 1 request, and after the
              limit is used up, for the same limits.

Raw numbers go to benchmarks/results/algos-<time>/ (latency.csv, memory.csv),
with summary.md and chart.svg. The limit is spread over an hour, so nothing
refills while a key is being measured. It uses throwaway keys in the database
you give it, and deletes them afterwards.
"""

import argparse
import csv
import math
import platform
import statistics
import time
import uuid
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

import redis

from tokenguard import Limit, algorithm_names, get_algorithm

HERE = Path(__file__).resolve().parent
CAPACITIES = (10, 100, 1_000, 10_000)
WINDOW = 3600  # seconds: long enough that nothing refills during a measurement


def percentile(sorted_values, q):
    """Nearest-rank percentile of an already sorted list."""
    index = math.ceil(q / 100 * len(sorted_values)) - 1
    return sorted_values[max(0, min(len(sorted_values) - 1, index))]


def summarise(samples):
    ordered = sorted(samples)
    return {
        "n": len(ordered),
        "mean": statistics.fmean(ordered),
        "p50": percentile(ordered, 50),
        "p95": percentile(ordered, 95),
        "p99": percentile(ordered, 99),
        "max": ordered[-1],
    }


def timed(fn, calls, warmup=50):
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(calls):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1e6)
    return samples


def memory_of(client, prefix):
    """MEMORY USAGE of the one key under `prefix`."""
    keys = list(client.scan_iter(f"{prefix}*"))
    if len(keys) != 1:
        raise RuntimeError(f"expected one key under {prefix}, found {keys}")
    return client.execute_command("MEMORY", "USAGE", keys[0])


def fill(client, algo, key, rule):
    """Use up the limit of `key`, the way `capacity` requests of cost 1 would.

    A sliding window needs the entries one request at a time, and each request
    reads all the earlier ones, so filling 10,000 through check() is quadratic
    and takes minutes. Its state is just a sorted set, so that one is written
    straight in the same format ("<id>:<cost>" scored by time).
    """
    capacity = int(rule.capacity)
    if algo.name == "sliding_window":
        now = time.time()
        pipe = client.pipeline(transaction=False)
        for i in range(capacity):
            pipe.execute_command(
                "ZADD", algo._key(key), now + i * 1e-6, f"{uuid.uuid4().hex}:1"
            )
        pipe.execute_command("PEXPIRE", algo._key(key), WINDOW * 1000)
        pipe.execute()
    else:
        algo.check(key, capacity, rule)  # one request that costs the whole limit


def measure_memory(client, prefix, capacities):
    """[(algorithm, requests, bytes)]: after 1 request, and with each limit full."""
    rows = []
    for name in algorithm_names():
        one = get_algorithm(name, client, key_prefix=f"{prefix}{name}:one:")
        one.check("k", 1, Limit(capacities[0], capacities[0] / WINDOW))
        rows.append((name, 1, memory_of(client, f"{prefix}{name}:one:")))
        for capacity in capacities:
            tag = f"{prefix}{name}:mem{capacity}:"
            algo = get_algorithm(name, client, key_prefix=tag)
            fill(client, algo, "k", Limit(capacity, capacity / WINDOW))
            rows.append((name, capacity, memory_of(client, tag)))
    return rows


def calls_for(capacity, calls):
    """Big sliding-window keys are slow to read: fewer samples there."""
    return calls if capacity <= 1_000 else min(calls, 500)


def time_check(algo, key, rule, calls):
    return summarise(timed(lambda: algo.check(key, 1, rule), calls))


def time_new_keys(algo, rule, calls):
    return summarise(timed(lambda: algo.check(uuid.uuid4().hex, 1, rule), calls))


def measure_latency(client, prefix, capacities, calls):
    """[(algorithm, case, capacity, stats)] for new keys and for full keys."""
    rows = []
    for name in algorithm_names():
        algo = get_algorithm(name, client, key_prefix=f"{prefix}{name}:lat:")
        small = Limit(capacities[0], capacities[0] / WINDOW)
        rows.append((name, "new key", 0, time_new_keys(algo, small, calls)))
        for capacity in capacities:
            rule = Limit(capacity, capacity / WINDOW)
            key = f"full{capacity}"
            fill(client, algo, key, rule)
            rows.append(
                (name, "full key", capacity, time_check(algo, key, rule, calls))
            )
    return rows


def fmt_capacity(n):
    return f"{n // 1000}k" if n >= 1000 and n % 1000 == 0 else str(n)


def render_markdown(memory, latency, meta):
    names = list(dict.fromkeys(row[0] for row in memory))
    capacities = sorted({row[1] for row in memory if row[1] > 1})
    mem = {(n, r): b for n, r, b in memory}
    lat = {(n, case, cap): s for n, case, cap, s in latency}
    lines = [
        "# Algorithm benchmarks",
        "",
        f"- measured: {meta['when']}",
        f"- machine: {meta['platform']}, Python {meta['python']}",
        f"- redis: {meta['redis']}, {meta['calls']} calls per case",
        "",
        "## Memory per key (bytes, Redis MEMORY USAGE)",
        "",
        "A key whose limit is used up. The token bucket and the fixed window are "
        "one fixed-size value; the sliding window keeps one entry per request.",
        "",
        "| algorithm | after 1 request | "
        + " | ".join(f"limit {fmt_capacity(c)} full" for c in capacities)
        + " |",
        "|---|---:|" + "---:|" * len(capacities),
    ]
    for n in names:
        cells = " | ".join(f"{mem[(n, c)]:,}" for c in capacities)
        lines.append(f"| {n} | {mem[(n, 1)]:,} | {cells} |")
    lines += [
        "",
        "## Latency per check() call (microseconds, network included)",
        "",
        "| algorithm | case | calls | p50 | p95 | p99 | max |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for n in names:
        cases = [("new key", 0)] + [("full key", c) for c in capacities]
        for case, cap in cases:
            s = lat[(n, case, cap)]
            label = case if cap == 0 else f"{case}, limit {fmt_capacity(cap)}"
            lines.append(
                f"| {n} | {label} | {s['n']} | {s['p50']:.0f} | {s['p95']:.0f} "
                f"| {s['p99']:.0f} | {s['max']:.0f} |"
            )
    return "\n".join(lines) + "\n"


COLORS = {
    "token_bucket": "#2563eb",
    "fixed_window": "#d97706",
    "sliding_window": "#059669",
}
FALLBACK = ("#7c3aed", "#db2777", "#475569")


def _decades(low, high):
    lo = math.floor(math.log10(max(low, 1e-9)))
    hi = math.ceil(math.log10(max(high, 1e-9)))
    return lo, max(hi, lo + 1)


def _text(x, y, text, css, anchor="start", fill=None):
    extra = f' fill="{fill}"' if fill else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{css}" '
        f'text-anchor="{anchor}"{extra}>{escape(str(text))}</text>'
    )


def _panel(x0, y0, w, h, title, unit, series, categories):
    """One log-y line chart. series = {name: [value per category]}."""
    values = [v for line in series.values() for v in line]
    lo, hi = _decades(min(values), max(values))

    def ypos(v):
        return y0 + h - (math.log10(max(v, 1e-9)) - lo) / (hi - lo) * h

    def xpos(i):
        return x0 + (i + 0.5) * w / len(categories)

    out = [_text(x0 - 40, y0 - 14, f"{title} ({unit})", "t")]
    for d in range(lo, hi + 1):
        y = ypos(10.0**d)
        out.append(
            f'<line x1="{x0}" x2="{x0 + w}" y1="{y:.1f}" y2="{y:.1f}" class="g"/>'
        )
        out.append(_text(x0 - 8, y + 4, f"{10**d:,}", "a", "end"))
    for i, cat in enumerate(categories):
        out.append(_text(xpos(i), y0 + h + 18, cat, "a", "middle"))
    out.append(
        _text(x0 + w / 2, y0 + h + 38, "limit (requests per key)", "a", "middle")
    )
    extra = iter(FALLBACK)
    labels = []
    for name, line in series.items():
        color = COLORS.get(name) or next(extra, "#334155")
        points = " ".join(f"{xpos(i):.1f},{ypos(v):.1f}" for i, v in enumerate(line))
        out.append(
            f'<polyline points="{points}" fill="none" stroke="{color}" '
            'stroke-width="2"/>'
        )
        for i, v in enumerate(line):
            out.append(
                f'<circle cx="{xpos(i):.1f}" cy="{ypos(v):.1f}" r="3" fill="{color}"/>'
            )
        labels.append([ypos(line[-1]) + 4, name, color])
    labels.sort()
    for before, label in zip(
        labels, labels[1:], strict=False
    ):  # keep end labels 14px apart
        label[0] = max(label[0], before[0] + 14)
    for y, name, color in labels:
        out.append(_text(xpos(len(categories) - 1) + 10, y, name, "l", fill=color))
    return out


def render_svg(memory, latency):
    """Two panels: memory of a full key, and p50 latency of a check on a full key."""
    names = list(dict.fromkeys(row[0] for row in memory))
    capacities = sorted({row[1] for row in memory if row[1] > 1})
    mem = {(n, r): b for n, r, b in memory}
    lat = {(n, case, cap): s["p50"] for n, case, cap, s in latency}
    memory_series = {n: [mem[(n, c)] for c in capacities] for n in names}
    latency_series = {n: [lat[(n, "full key", c)] for c in capacities] for n in names}
    cats = [fmt_capacity(c) for c in capacities]
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 300" '
        'width="960" height="300" font-family="system-ui, sans-serif">',
        "<style>.t{font-size:14px;font-weight:600;fill:#111}"
        ".a{font-size:11px;fill:#555}.l{font-size:12px;font-weight:600}"
        ".g{stroke:#e5e5e5;stroke-width:1}</style>",
        '<rect width="960" height="300" fill="#fff"/>',
    ]
    parts += _panel(
        70, 50, 300, 210, "Memory of a full key", "bytes", memory_series, cats
    )
    parts += _panel(
        640, 50, 200, 210, "check() on a full key", "median microseconds",
        latency_series, cats,
    )  # fmt: skip
    parts.append("</svg>")
    return "\n".join(parts)


def redis_version(client):
    try:
        return client.info("server")["redis_version"]
    except Exception:
        return "unknown"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("url", nargs="?", default="redis://127.0.0.1:6379/5")
    parser.add_argument("--calls", type=int, default=2000)
    parser.add_argument("--docs", help="folder to write algorithm-benchmarks.* into")
    args = parser.parse_args(argv)

    client = redis.Redis.from_url(args.url, decode_responses=True)
    client.ping()
    prefix = f"ab:{uuid.uuid4().hex[:8]}:"
    try:
        memory = measure_memory(client, prefix, CAPACITIES)
        latency = measure_latency(client, prefix, CAPACITIES, args.calls)
    finally:
        for key in client.scan_iter(f"{prefix}*"):
            client.delete(key)

    meta = {
        "when": f"{datetime.now():%Y-%m-%d %H:%M}",
        "platform": platform.platform(),
        "python": platform.python_version(),
        "redis": redis_version(client),
        "calls": args.calls,
    }
    out = HERE / "results" / f"algos-{datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True)
    with open(out / "memory.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["algorithm", "requests_in_key", "bytes"])
        writer.writerows(memory)
    with open(out / "latency.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        keys = ("mean", "p50", "p95", "p99", "max")
        writer.writerow(["algorithm", "case", "limit"] + [f"{k}_us" for k in keys])
        for name, case, cap, s in latency:
            writer.writerow([name, case, cap] + [f"{s[k]:.1f}" for k in keys])
    text = render_markdown(memory, latency, meta)
    svg = render_svg(memory, latency)
    (out / "summary.md").write_text(text)
    (out / "chart.svg").write_text(svg)
    if args.docs:
        docs = Path(args.docs)
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "algorithm-benchmarks.svg").write_text(svg)
        picture = "![memory and latency by limit](algorithm-benchmarks.svg)"
        title = "# Algorithm benchmarks\n"
        page = text.replace(title, f"{title}\n{picture}\n", 1)
        (docs / "algorithm-benchmarks.md").write_text(page)
        print(f"Wrote {docs / 'algorithm-benchmarks.md'}")
    print(text)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
