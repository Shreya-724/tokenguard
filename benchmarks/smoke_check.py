"""Pass or fail a quick load test (used by CI).

    python benchmarks/run_bench.py --users 10 --duration 8 --repeats 1 --label ci
    python benchmarks/smoke_check.py benchmarks/results/<run>-ci

This is a smoke test, not a benchmark: it asks "does the limiter still behave
under concurrent traffic?", not "how fast is it?". It fails when:

    * any request failed (5xx, timeout, connection error), or the server was
      too slow to be plausible (a floor far below any real machine);
    * the `allowed` scenario returned any 429, or no 200 at all;
    * the `blocked` scenario let through more than a few percent of requests;
    * the `distinct` scenario (every caller new) refused more than a few percent.
"""

import sys
from pathlib import Path

import report

MIN_RPS = 20  # far below any healthy run, even a small CI machine
BLOCKED_AT_LEAST = 0.90  # the blocked scenario: share of 429s
DISTINCT_BLOCKED_AT_MOST = 0.05


def check(results):
    """A list of problems found in report.collect() output (empty = pass)."""
    problems = []
    if not results:
        return ["no results found"]
    for scenario, modes in sorted(results.items()):
        for mode in ("baseline", "limited"):
            run = modes.get(mode)
            if run is None:
                continue
            where = f"{scenario}/{mode}"
            if run["failures"]:
                problems.append(f"{where}: {run['failures']} failed requests")
            if run["rps"] < MIN_RPS:
                problems.append(f"{where}: only {run['rps']:.0f} req/s")
        limited = modes.get("limited")
        if limited is None:
            problems.append(f"{scenario}: no limited run")
            continue
        ok = limited["status"].get("200", 0)
        refused = limited["status"].get("429", 0)
        total = ok + refused
        if not total:
            problems.append(f"{scenario}/limited: no status counts were recorded")
            continue
        if scenario == "allowed" and (refused or not ok):
            problems.append(f"allowed: {ok} ok, {refused} refused (expected all ok)")
        if scenario == "blocked" and refused / total < BLOCKED_AT_LEAST:
            problems.append(f"blocked: only {refused / total:.0%} refused")
        if scenario == "distinct" and refused / total > DISTINCT_BLOCKED_AT_MOST:
            problems.append(f"distinct: {refused / total:.0%} refused (new callers)")
    return problems


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        sys.exit(__doc__)
    results = report.collect(Path(argv[0]))
    problems = check(results)
    for scenario, modes in sorted(results.items()):
        for mode in ("baseline", "limited"):
            if mode in modes:
                run = modes[mode]
                print(
                    f"{scenario:9}{mode:9}{run['rps']:8.0f} req/s  "
                    f"failures={run['failures']}  status={run['status']}"
                )
    if problems:
        print("\nSMOKE TEST FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        sys.exit(1)
    print("\nsmoke test passed")


if __name__ == "__main__":
    main()
