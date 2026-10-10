from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

import pytest

from _workers import build, run_batch

CAPACITY = 100
TOTAL = 1000
RATE = 0.0001  # refill is negligible during the test, so exactly CAPACITY must pass


@pytest.mark.parametrize("attempt", range(20))
def test_lua_exactly_capacity_allowed_with_threads(redis_url, key, attempt):
    bucket = build("lua", redis_url, key, CAPACITY, RATE)
    with ThreadPoolExecutor(max_workers=50) as pool:
        results = list(pool.map(lambda _: bucket.allow().allowed, range(TOTAL)))
    assert sum(results) == CAPACITY


@pytest.mark.parametrize("attempt", range(5))
def test_lua_exactly_capacity_allowed_with_processes(redis_url, key, attempt):
    jobs = [("lua", redis_url, key, CAPACITY, RATE, TOTAL // 8)] * 8
    with ProcessPoolExecutor(max_workers=8) as pool:
        allowed = sum(pool.map(run_batch, jobs))
    assert allowed == CAPACITY
