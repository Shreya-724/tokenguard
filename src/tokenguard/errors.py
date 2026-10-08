"""Exceptions raised by tokenguard."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

import redis

F = TypeVar("F", bound=Callable[..., Any])


class RedisUnavailableError(Exception):
    """Redis could not be reached (down, refused, or timed out)."""


def wrap_redis_errors(func: F) -> F:
    """Turn low-level redis-py connection errors into RedisUnavailableError."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except (redis.ConnectionError, redis.TimeoutError) as exc:
            raise RedisUnavailableError(f"Redis unavailable: {exc}") from exc

    return wrapper  # type: ignore[return-value]
