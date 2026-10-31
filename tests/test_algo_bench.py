"""The algorithm benchmark: its maths, its chart, and its memory measurements."""

import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "benchmarks"))
import algo_bench  # noqa: E402

from tokenguard import Limit, get_algorithm  # noqa: E402


def test_percentile_is_nearest_rank():
    data = list(range(1, 101))
    assert algo_bench.percentile(data, 50) == 50
    assert algo_bench.percentile(data, 99) == 99
    assert algo_bench.percentile(data, 100) == 100
    assert algo_bench.percentile([7], 99) == 7


def test_summarise_gives_the_counts_and_the_order():
    s = algo_bench.summarise([5, 1, 3, 2, 4])
    assert s["n"] == 5 and s["p50"] == 3 and s["max"] == 5 and s["mean"] == 3


def fake_results():
    memory, latency = [], []
    sizes = {"token_bucket": 136, "fixed_window": 120, "sliding_window": None}
    for name, flat in sizes.items():
        memory.append((name, 1, 120))
        for cap in (10, 100):
            memory.append((name, cap, flat or cap * 100))
            stats = {"n": 5, "mean": 1, "p50": 80 + cap, "p95": 9, "p99": 9, "max": 9}
            latency.append((name, "full key", cap, stats))
        latency.append((name, "new key", 0, stats))
    return memory, latency


def test_the_chart_is_valid_svg_and_names_every_algorithm():
    svg = algo_bench.render_svg(*fake_results())
    root = ET.fromstring(svg)  # raises if it is not well formed
    assert root.tag.endswith("svg")
    for name in ("token_bucket", "fixed_window", "sliding_window"):
        assert name in svg


def test_the_markdown_has_both_tables():
    meta = {"when": "now", "platform": "p", "python": "3", "redis": "7", "calls": 5}
    text = algo_bench.render_markdown(*fake_results(), meta)
    assert "| sliding_window | 120 | 1,000 | 10,000 |" in text
    assert "| token_bucket | full key, limit 100 | 5 | 180 |" in text


@pytest.fixture
def prefix(redis_client):
    p = f"test:{uuid.uuid4().hex}:"
    yield p
    for key in redis_client.scan_iter(f"{p}*"):
        redis_client.delete(key)


def test_sliding_memory_grows_with_the_limit_and_the_others_do_not(
    redis_client, prefix
):
    rows = algo_bench.measure_memory(redis_client, prefix, (10, 100))
    size = {(name, requests): b for name, requests, b in rows}
    assert size[("sliding_window", 100)] > 4 * size[("sliding_window", 10)]
    # one fixed-size value: the limit does not change it (allocator rounding aside)
    assert abs(size[("token_bucket", 100)] - size[("token_bucket", 10)]) <= 32
    assert abs(size[("fixed_window", 100)] - size[("fixed_window", 10)]) <= 32


def test_writing_the_sliding_log_directly_matches_real_requests(redis_client, prefix):
    """The shortcut used to fill big limits must produce the same state."""
    rule = Limit(100, 100 / algo_bench.WINDOW)
    real = get_algorithm("sliding_window", redis_client, key_prefix=f"{prefix}real:")
    for _ in range(100):
        real.check("k", 1, rule)
    direct = get_algorithm("sliding_window", redis_client, key_prefix=f"{prefix}fast:")
    algo_bench.fill(redis_client, direct, "k", rule)
    real_key, fast_key = real._key("k"), direct._key("k")
    assert redis_client.zcard(real_key) == redis_client.zcard(fast_key) == 100
    bytes_real = algo_bench.memory_of(redis_client, f"{prefix}real:")
    bytes_fast = algo_bench.memory_of(redis_client, f"{prefix}fast:")
    assert bytes_fast == bytes_real
    # and the limit really is used up: the next request is refused
    assert not direct.check("k", 1, rule).allowed
