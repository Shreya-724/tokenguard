"""The smoke-test verdicts, on made-up results."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))
import smoke_check  # noqa: E402


def run(rps=500.0, failures=0, **status):
    return {"rps": rps, "failures": failures, "status": status}


def healthy():
    return {
        "allowed": {"baseline": run(**{"200": 900}), "limited": run(**{"200": 800})},
        "blocked": {"limited": run(**{"200": 3, "429": 997})},
        "distinct": {"limited": run(**{"200": 700})},
    }


def test_a_healthy_run_passes():
    assert smoke_check.check(healthy()) == []


def test_no_results_is_a_failure():
    assert smoke_check.check({}) == ["no results found"]


def test_failed_requests_fail_the_run():
    results = healthy()
    results["allowed"]["limited"]["failures"] = 2
    assert any("2 failed" in p for p in smoke_check.check(results))


def test_a_painfully_slow_server_fails_the_run():
    results = healthy()
    results["allowed"]["limited"]["rps"] = 3
    assert any("3 req/s" in p for p in smoke_check.check(results))


def test_allowed_traffic_must_not_be_refused():
    results = healthy()
    results["allowed"]["limited"]["status"] = {"200": 700, "429": 100}
    assert any(p.startswith("allowed") for p in smoke_check.check(results))


def test_blocked_traffic_must_mostly_be_refused():
    results = healthy()
    results["blocked"]["limited"]["status"] = {"200": 600, "429": 400}
    assert any(p.startswith("blocked") for p in smoke_check.check(results))


def test_new_callers_must_not_be_refused():
    results = healthy()
    results["distinct"]["limited"]["status"] = {"200": 500, "429": 500}
    assert any(p.startswith("distinct") for p in smoke_check.check(results))


def test_missing_status_counts_are_reported_not_ignored():
    results = healthy()
    results["blocked"]["limited"]["status"] = {}
    assert any("no status counts" in p for p in smoke_check.check(results))
