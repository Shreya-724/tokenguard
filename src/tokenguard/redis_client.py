"""Helper to build a pooled Redis client with sane timeouts."""

from __future__ import annotations

import redis


def create_client(
    url: str = "redis://localhost:6379/0",
    *,
    max_connections: int = 50,
    socket_timeout: float = 0.5,
    socket_connect_timeout: float = 0.5,
) -> redis.Redis:
    """Pooled client. Waits for a free connection instead of erroring when busy."""
    pool = redis.BlockingConnectionPool.from_url(
        url,
        max_connections=max_connections,
        timeout=2,
        socket_timeout=socket_timeout,
        socket_connect_timeout=socket_connect_timeout,
        decode_responses=True,
    )
    return redis.Redis(connection_pool=pool)
