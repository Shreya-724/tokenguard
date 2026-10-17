"""tokenguard: a token-aware, Redis-backed rate limiter for Django."""

from tokenguard.algorithms import Limit, algorithm_names, get_algorithm
from tokenguard.bucket import Decision, TokenBucket
from tokenguard.clock import Clock, FakeClock, SystemClock, WallClock
from tokenguard.errors import RedisUnavailableError
from tokenguard.redis_bucket import NaiveRedisTokenBucket, RedisTokenBucket
from tokenguard.rulestore import RuleStore

__version__ = "0.4.0"  # keep equal to pyproject.toml (tests/test_version.py checks)

__all__ = [
    "Clock",
    "Decision",
    "FakeClock",
    "Limit",
    "NaiveRedisTokenBucket",
    "RedisTokenBucket",
    "RedisUnavailableError",
    "RuleStore",
    "SystemClock",
    "TokenBucket",
    "WallClock",
    "__version__",
    "algorithm_names",
    "get_algorithm",
]
