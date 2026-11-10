"""Which Redis failures count as "unavailable" (and so fail open or closed)."""

import uuid

import pytest
import redis

from tokenguard import Limit, get_algorithm
from tokenguard.errors import RedisUnavailableError, is_unavailable, wrap_redis_errors


@pytest.mark.parametrize(
    "exc",
    [
        redis.ConnectionError("refused"),
        redis.TimeoutError("slow"),
        redis.ResponseError("OOM command not allowed when used memory > 'maxmemory'."),
        redis.ResponseError("READONLY You can't write against a read only replica."),
        redis.ResponseError("BUSY Redis is busy running a script."),
        redis.ResponseError("MASTERDOWN Link with MASTER is down"),
        redis.ResponseError("LOADING Redis is loading the dataset in memory"),
    ],
)
def test_outages_are_unavailable(exc):
    assert is_unavailable(exc)


@pytest.mark.parametrize(
    "exc",
    [
        redis.ResponseError("WRONGTYPE Operation against a key holding the wrong kind"),
        redis.ResponseError("ERR Error running script: attempt to index a nil value"),
        ValueError("OOM"),  # not a Redis error at all
    ],
)
def test_bugs_are_not_unavailable(exc):
    assert not is_unavailable(exc)


def test_the_exact_exceptions_real_redis_py_raises_count():
    """redis-py drops the leading word, so "OOM" is not in str(exc)."""
    exceptions = pytest.importorskip("redis.exceptions")
    oom = exceptions.OutOfMemoryError(
        "command not allowed when used memory > 'maxmemory'."
    )
    assert "OOM" not in str(oom)
    assert is_unavailable(oom)
    assert is_unavailable(
        exceptions.ReadOnlyError("You can't write against a read only replica.")
    )
    assert not is_unavailable(exceptions.ResponseError("WRONGTYPE nope"))


def test_the_wrapper_converts_outages_and_passes_bugs_through():
    @wrap_redis_errors
    def oom():
        raise redis.ResponseError("OOM command not allowed")

    @wrap_redis_errors
    def bug():
        raise redis.ResponseError("WRONGTYPE nope")

    with pytest.raises(RedisUnavailableError):
        oom()
    with pytest.raises(redis.ResponseError):
        bug()


def config_get(client, name):
    reply = client.execute_command("CONFIG", "GET", name)
    if isinstance(reply, dict):  # redis-py turns the reply into a dict
        return reply[name]
    return reply[reply.index(name) + 1]


def used_memory(client):
    info = client.execute_command("INFO", "memory")
    if isinstance(info, dict):  # redis-py parses INFO into a dict
        return int(info["used_memory"])
    for line in str(info).splitlines():
        if line.startswith("used_memory:"):
            return int(line.split(":")[1])
    raise RuntimeError("no used_memory in INFO")


def test_a_full_redis_with_noeviction_means_unavailable_not_a_crash(redis_client):
    """Real Redis at its memory limit refuses writes; the limiter must say so."""
    try:
        old = {
            n: config_get(redis_client, n) for n in ("maxmemory", "maxmemory-policy")
        }
    except redis.ResponseError:
        pytest.skip("CONFIG is not allowed on this Redis")
    prefix = f"test:{uuid.uuid4().hex}:"
    try:
        redis_client.execute_command("CONFIG", "SET", "maxmemory-policy", "noeviction")
        redis_client.execute_command(
            "CONFIG", "SET", "maxmemory", str(used_memory(redis_client) + 300_000)
        )
        filler = 0
        try:
            while filler < 100_000:  # fill up to the limit with plain keys
                redis_client.execute_command("SET", f"{prefix}fill:{filler}", "x" * 100)
                filler += 1
        except redis.ResponseError as exc:
            assert is_unavailable(exc), repr(exc)
        else:
            pytest.fail("Redis never reached its memory limit")
                        # The fill proved Redis can hit its limit, but memory drifts right at
            # the edge. Push the limit well below usage so every write is refused.
            redis_client.execute_command(
                "CONFIG", "SET", "maxmemory", str(max(1, used_memory(redis_client) // 2))
            )
            algo = get_algorithm("token_bucket", redis_client, key_prefix=prefix)
            with pytest.raises(RedisUnavailableError):
             algo.check("someone", 1, Limit(5, 1))
    finally:
        redis_client.execute_command("CONFIG", "SET", "maxmemory", old["maxmemory"])
        redis_client.execute_command(
            "CONFIG", "SET", "maxmemory-policy", old["maxmemory-policy"]
        )
        for key in redis_client.scan_iter(f"{prefix}*"):
            redis_client.delete(key)
