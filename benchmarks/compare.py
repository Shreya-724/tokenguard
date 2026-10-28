"""Before/after table from two load-test runs (Week 7, Day 4).

    python benchmarks/compare.py benchmarks/results/<before> benchmarks/results/<after>
    python benchmarks/compare.py <before> <after> --readme README.md

Prints a Markdown table. With --readme it puts the table between the markers

    <!-- bench:start -->
    <!-- bench:end -->

in that file, replacing whatever was there. The baseline rows are the noise
check: the baseline did not change between runs, so if it moved, the machine
did, and the comparison cannot be trusted.
"""

import argparse
import json
import sys
from pathlib import Path

import report

START, END = "<!-- bench:start -->", "<!-- bench:end -->"
NOISE_LIMIT = 10.0  # % the baseline may move before the comparison is distrusted


def pct(before, after):
    return (after - before) / before * 100 if before else 0.0


def scenario_rows(before, after):
    """Rows of (label, before, after, change) for one scenario, or None."""
    b, a = before.get("limited"), after.get("limited")
    if not b or not a:
        return None
    rows = [
        ("limited: req/s", b["rps"], a["rps"], f"{pct(b['rps'], a['rps']):+.1f}%"),
        (
            "limited: ms/req",
            b["ms_per_req"],
            a["ms_per_req"],
            f"{pct(b['ms_per_req'], a['ms_per_req']):+.1f}%",
        ),
    ]
    ob, oa = before.get("overhead"), after.get("overhead")
    if ob and oa:
        rows.append(
            (
                "limiter cost: ms/req over baseline",
                ob["ms_per_req"],
                oa["ms_per_req"],
                f"{oa['ms_per_req'] - ob['ms_per_req']:+.2f} ms",
            )
        )
        rows.append(
            (
                "limiter cost: req/s vs baseline",
                ob["rps_change_pct"],
                oa["rps_change_pct"],
                f"{oa['rps_change_pct'] - ob['rps_change_pct']:+.1f} pts",
            )
        )
    bb, ba = before.get("baseline"), after.get("baseline")
    if bb and ba:
        rows.append(
            (
                "baseline: req/s (noise check)",
                bb["rps"],
                ba["rps"],
                f"{pct(bb['rps'], ba['rps']):+.1f}%",
            )
        )
    return rows


def noisy(before, after):
    """Scenarios whose baseline moved more than NOISE_LIMIT between the runs."""
    bad = []
    for name in before:
        b, a = before[name].get("baseline"), after.get(name, {}).get("baseline")
        if b and a and abs(pct(b["rps"], a["rps"])) > NOISE_LIMIT:
            bad.append((name, pct(b["rps"], a["rps"])))
    return bad


def render(before, after, meta_before=None, meta_after=None):
    meta_before, meta_after = meta_before or {}, meta_after or {}
    lines = []
    for key in ("platform", "cpus", "redis", "users"):
        if key in meta_after:
            lines.append(f"- {key}: {meta_after[key]}")
    for label, meta in (("before", meta_before), ("after", meta_after)):
        bits = [f"{k}={meta[k]}" for k in ("metrics", "metrics_flush") if k in meta]
        lines.append(f"- {label}: {meta.get('started', '?')} ({', '.join(bits)})")
    lines.append("")
    for name in sorted(after):
        rows = scenario_rows(before.get(name, {}), after[name])
        if not rows:
            continue
        lines += [
            f"**{name}**",
            "",
            "| | before | after | change |",
            "|---|---:|---:|---:|",
        ]
        lines += [f"| {r[0]} | {r[1]:.2f} | {r[2]:.2f} | {r[3]} |" for r in rows]
        lines.append("")
    for name, moved in noisy(before, after):
        lines.append(
            f"> **Warning:** the `{name}` baseline moved {moved:+.0f}% between the "
            "runs. The machine was not steady; repeat before quoting this."
        )
    return "\n".join(lines).rstrip() + "\n"


def inject(text, table):
    """Replace what is between the bench markers with the table."""
    if START not in text or END not in text:
        raise ValueError(f"the file needs the markers {START} and {END}")
    head, rest = text.split(START, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{START}\n\n{table}\n{END}{tail}"


def load(run_dir):
    run_dir = Path(run_dir)
    if not (run_dir / "raw").is_dir():
        sys.exit(
            f"{run_dir} is not a run folder (no raw/ inside). Use a real folder "
            "name from benchmarks/results, e.g. 20261027-213852-before."
        )
    meta_path = run_dir / "meta.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return report.collect(run_dir), meta


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("before")
    parser.add_argument("after")
    parser.add_argument("--readme", help="file with the bench markers to fill in")
    args = parser.parse_args(argv)
    before, meta_before = load(args.before)
    after, meta_after = load(args.after)
    if not any(before.values()) or not any(after.values()):
        sys.exit("a run folder has no results (no *_stats.csv files in raw/).")
    table = render(before, after, meta_before, meta_after)
    print(table)
    if args.readme:
        path = Path(args.readme)
        try:
            path.write_text(inject(path.read_text(encoding="utf-8"), table), "utf-8")
        except ValueError as exc:
            sys.exit(str(exc))
        print(f"Updated {path}")


if __name__ == "__main__":
    main()
