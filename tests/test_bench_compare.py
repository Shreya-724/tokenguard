"""The before/after table: arithmetic, the noise warning, and the README markers."""

import json
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "benchmarks"))
sys.path.insert(0, str(HERE))
import compare  # noqa: E402
import report  # noqa: E402

from test_bench_report import stats_csv  # noqa: E402


def run(tmp_path, name, baseline_rps, limited_rps, meta=None):
    raw = tmp_path / name / "raw"
    raw.mkdir(parents=True)
    stats_csv(
        raw / "baseline_allowed_r1_stats.csv", 1000, 0, baseline_rps, 4, 4, 8, 9, 9
    )
    stats_csv(raw / "limited_allowed_r1_stats.csv", 1000, 0, limited_rps, 6, 6, 9, 9, 9)
    (tmp_path / name / "meta.json").write_text(json.dumps(meta or {}))
    return tmp_path / name


def test_rows_show_the_change_in_the_limiter_cost(tmp_path):
    before = report.collect(run(tmp_path, "before", 250, 150))
    after = report.collect(run(tmp_path, "after", 250, 200))
    rows = {r[0]: r for r in compare.scenario_rows(before["allowed"], after["allowed"])}
    assert rows["limited: req/s"][1:3] == (150, 200)
    assert rows["limited: req/s"][3] == "+33.3%"
    cost = rows["limiter cost: ms/req over baseline"]
    assert cost[1] == pytest.approx(1000 / 150 - 1000 / 250)
    assert cost[2] == pytest.approx(1000 / 200 - 1000 / 250)
    assert cost[3] == "-1.67 ms"
    assert rows["baseline: req/s (noise check)"][3] == "+0.0%"


def test_a_moving_baseline_is_flagged(tmp_path):
    before = report.collect(run(tmp_path, "before", 250, 150))
    after = report.collect(run(tmp_path, "after", 190, 150))
    assert compare.noisy(before, after) == [("allowed", pytest.approx(-24.0))]
    assert "Warning" in compare.render(before, after)


def test_a_steady_baseline_is_not_flagged(tmp_path):
    before = report.collect(run(tmp_path, "before", 250, 150))
    after = report.collect(run(tmp_path, "after", 255, 200))
    assert compare.noisy(before, after) == []
    assert "Warning" not in compare.render(before, after)


def test_inject_replaces_only_what_is_between_the_markers():
    text = f"intro\n{compare.START}\nold table\n{compare.END}\noutro\n"
    out = compare.inject(text, "NEW\n")
    assert out == f"intro\n{compare.START}\n\nNEW\n\n{compare.END}\noutro\n"
    again = compare.inject(out, "NEWER\n")  # running it twice replaces, not appends
    assert again.count(compare.START) == 1 and "NEWER" in again
    assert "\nNEW\n" not in again
    assert "old table" not in out and "intro" in out and "outro" in out


def test_inject_without_markers_is_an_error():
    with pytest.raises(ValueError):
        compare.inject("no markers here", "x")


def test_main_writes_the_readme(tmp_path):
    before = run(tmp_path, "before", 250, 150, {"metrics": True, "metrics_flush": 0})
    after = run(tmp_path, "after", 250, 200, {"metrics": True, "metrics_flush": 0.2})
    readme = tmp_path / "README.md"
    readme.write_text(f"# x\n{compare.START}\n{compare.END}\n")
    compare.main([str(before), str(after), "--readme", str(readme)])
    text = readme.read_text()
    assert "| limited: req/s | 150.00 | 200.00 | +33.3% |" in text
    assert "metrics_flush=0.2" in text
