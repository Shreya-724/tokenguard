"""Errors, and the one place that decides which Redis failures mean "unavailable".

`RedisUnavailableError` is what the limiter raises when Redis cannot answer. The
fail-open / fail-closed setting then decides what happens to the request.

Two kinds of failure count as "cannot answer":

* the connection itself (refused, reset, timed out, still loading its data), and
* a server that is up but refuses the command in its current state: out of memory
  with `maxmemory-policy noeviction` (OOM), a read-only replica (READONLY), a busy
  script (BUSY), a master that is down (MASTERDOWN, CLUSTERDOWN).

Everything else (WRONGTYPE, a Lua script error, a bad argument) is a bug, not an
outage, and is allowed to raise so it gets noticed instead of being failed open.
"""

import functools

import redis

# The first word of the reply, as Redis sends it. Matched on the text so it works
# with every redis-py version, whichever subclass of ResponseError it raises.
_UNAVAILABLE_PREFIXES = (
    "OOM",
    "READONLY",
    "BUSY",
    "MASTERDOWN",
    "CLUSTERDOWN",
    "NOREPLICAS",
    "LOADING",
    "TRYAGAIN",
)


try:  # real redis-py; the classes it raises for these server replies
    from redis import exceptions as _exceptions
except ImportError:  # a minimal stand-in without the submodule
    _exceptions = None

# redis-py picks one of these from the first word of the reply and REMOVES that
# word from the message: a full Redis says "OOM command not allowed...", but
# str(OutOfMemoryError) is just "command not allowed when used memory...". So
# the classes are checked as well as the text.
_UNAVAILABLE_CLASSES = tuple(
    cls
    for name in ("OutOfMemoryError", "ReadOnlyError", "BusyLoadingError")
    if (cls := getattr(_exceptions, name, None)) is not None
)


class RedisUnavailableError(Exception):
    """Redis could not answer (down, timed out, out of memory, read-only...)."""


def is_unavailable(exc: BaseException) -> bool:
    """True for a Redis failure that means "cannot answer", not "a bug"."""
    if isinstance(exc, redis.ConnectionError | redis.TimeoutError):
        return True
    if _UNAVAILABLE_CLASSES and isinstance(exc, _UNAVAILABLE_CLASSES):
        return True
    if isinstance(exc, redis.ResponseError):
        text = str(exc).lstrip()
        return text.upper().startswith(_UNAVAILABLE_PREFIXES) or "'maxmemory'" in text
    return False


def wrap_redis_errors(func):
    """Turn "Redis cannot answer" failures into RedisUnavailableError."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except redis.RedisError as exc:
            if is_unavailable(exc):
                raise RedisUnavailableError(f"Redis unavailable: {exc}") from exc
            raise

    return wrapper
