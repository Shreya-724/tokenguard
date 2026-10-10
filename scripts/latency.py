"""Time single allow() calls and print p50/p95/p99 in milliseconds."""

import statistics
import time
import uuid

from tokenguard import NaiveRedisTokenBucket, RedisTokenBucket, TokenBucket
from tokenguard.redis_client import create_client

N = 5000


def measure(bucket) -> list[float]:
    samples = []
    for _ in range(N):
        t0 = time.perf_counter()
        bucket.allow()
        samples.append((time.perf_counter() - t0) * 1000)
    return samples


def report(name: str, samples: list[float]) -> None:
    q = statistics.quantiles(samples, n=100)
    print(f"{name:8} p50={q[49]:.3f}ms  p95={q[94]:.3f}ms  p99={q[98]:.3f}ms")


if __name__ == "__main__":
    client = create_client()
    k = uuid.uuid4().hex
    report("memory", measure(TokenBucket(10**9, 10**6)))
    report("naive", measure(NaiveRedisTokenBucket(client, f"lat:n:{k}", 10**9, 10**6)))
    report("lua", measure(RedisTokenBucket(client, f"lat:l:{k}", 10**9, 10**6)))
    client.delete(f"lat:n:{k}", f"lat:l:{k}")
