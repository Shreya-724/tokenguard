"""The load-test reporter: parsing, medians and the overhead arithmetic."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))
import report  # noqa: E402

HEADER = (
    "Type,Name,Request Count,Failure Count,Median Response Time,"
    "Average Response Time,Min Response Time,Max Response Time,"
    "Average Content Size,Requests/s,Failures/s,50%,66%,75%,80%,90%,95%,98%,"
    "99%,99.9%,99.99%,100%"
)


def stats_csv(path, requests, failures, rps, avg, p50, p95, p99, top):
    row = (
        f",Aggregated,{requests},{failures},{p50},{avg},1,{top},12,{rps},0,"
        f"{p50},{p50},{p50},{p50},{p95},{p95},{p99},{p99},{top},{top},{top}"
    )
    path.write_text(
        f"{HEADER}\nGET,/bench/allowed/,1,0,1,1,1,1,1,1,0,1,1,1,1,1,1,1,1,1,1,1\n{row}\n"
    )


def make_run(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    # baseline: 3 repeats, limited: 3 repeats (the middle value is the median)
    for repeat, rps in enumerate((1000, 1100, 900), start=1):
        stats_csv(
            raw / f"baseline_allowed_r{repeat}_stats.csv",
            30000,
            0,
            rps,
            4.0,
            4,
            8,
            12,
            50,
        )
        (raw / f"baseline_allowed_r{repeat}_status.json").write_text(
            json.dumps({"200": 30000})
        )
    for repeat, rps in enumerate((800, 850, 700), start=1):
        stats_csv(
            raw / f"limited_allowed_r{repeat}_stats.csv",
            24000,
            3,
            rps,
            5.5,
            5,
            10,
            20,
            90,
        )
        (raw / f"limited_allowed_r{repeat}_status.json").write_text(
            json.dumps({"200": 23000, "429": 1000})
        )
    return tmp_path


def test_parse_reads_the_aggregated_row_not_the_endpoint_row(tmp_path):
    path = tmp_path / "x_stats.csv"
    stats_csv(path, 500, 2, 49.5, 3.25, 3, 6, 9, 20)
    got = report.parse_stats(path)
    assert got == {
        "requests": 500, "failures": 2, "rps": 49.5, "avg": 3.25,
        "p50": 3.0, "p95": 6.0, "p99": 9.0, "max": 20.0,
    }  # fmt: skip


def test_parse_without_an_aggregated_row_is_an_error(tmp_path):
    path = tmp_path / "x_stats.csv"
    path.write_text(HEADER + "\n")
    with pytest.raises(ValueError):
        report.parse_stats(path)


def test_collect_takes_the_median_of_repeats(tmp_path):
    results = report.collect(make_run(tmp_path))["allowed"]
    assert results["baseline"]["rps"] == 1000
    assert results["limited"]["rps"] == 800
    assert (
        results["baseline"]["rps_min"] == 900 and results["baseline"]["rps_max"] == 1100
    )
    assert results["limited"]["failures"] == 9  # 3 per repeat, summed
    assert results["limited"]["status"] == {"200": 69000, "429": 3000}


def test_overhead_is_limited_minus_baseline(tmp_path):
    extra = report.collect(make_run(tmp_path))["allowed"]["overhead"]
    assert extra["rps_change_pct"] == pytest.approx(-20.0)
    assert extra["avg_ms"] == pytest.approx(1.5)
    assert extra["ms_per_req"] == pytest.approx(1000 / 800 - 1000 / 1000)
    assert extra["p50_ms"] == 1 and extra["p95_ms"] == 2 and extra["p99_ms"] == 8


def test_write_makes_summary_files(tmp_path):
    run = make_run(tmp_path)
    (run / "meta.json").write_text(json.dumps({"users": 50, "cpus": 8}))
    report.write(run)
    text = (run / "summary.md").read_text()
    assert "## allowed" in text and "**overhead**" in text and "-20.0%" in text
    assert "- users: 50" in text
    assert (
        json.loads((run / "summary.json").read_text())["allowed"]["limited"]["rps"]
        == 800
    )


def test_a_scenario_with_only_one_mode_has_no_overhead(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    stats_csv(raw / "limited_blocked_r1_stats.csv", 100, 0, 10, 1, 1, 2, 3, 4)
    results = report.collect(tmp_path)
    assert "overhead" not in results["blocked"]
    assert "baseline" not in results["blocked"]
