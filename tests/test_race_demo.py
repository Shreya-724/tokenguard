"""scripts/race_demo.py: the summary maths, its guards, and one real round."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import race_demo  # noqa: E402

from tokenguard import algorithm_names  # noqa: E402


def test_summarize_counts_rounds_over_the_limit():
    s = race_demo.summarize([100, 130, 100, 180], limit=100)
    assert (s["min"], s["max"]) == (100, 180)
    assert s["rounds_over"] == 2
    assert s["worst_over"] == 80
    assert s["mean"] == 127.5


def test_refuses_database_zero():
    with pytest.raises(SystemExit):
        race_demo.main(["--redis", "redis://127.0.0.1:6379/0"])


def test_needs_more_attempts_than_the_limit():
    with pytest.raises(SystemExit):
        race_demo.main(["--processes", "2", "--attempts", "5", "--limit", "100"])


@pytest.mark.parametrize("kind", list(algorithm_names()))
def test_every_atomic_algorithm_allows_exactly_the_limit(kind, redis_url):
    allowed = race_demo.one_round(kind, redis_url, processes=4, limit=20, attempts=15)
    assert allowed == 20
