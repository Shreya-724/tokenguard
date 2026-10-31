"""The audit script: classify keys, find the immortal ones, fix them."""

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import tokenguard_audit as audit  # noqa: E402

from tokenguard import Limit, get_algorithm  # noqa: E402


@pytest.fixture
def prefix(redis_client):
    p = f"auditest{uuid.uuid4().hex[:8]}"
    yield p
    for key in redis_client.scan_iter(f"{p}:*"):
        redis_client.delete(key)


def test_kinds_are_told_apart():
    kinds = {
        "tg:sw:api:ip:1": "sliding window",
        "tg:fw:api:ip:1": "fixed window",
        "tg:metrics:123": "metrics",
        "tg:metrics:top:123": "metrics",
        "tg:{rules}": "live rules",
        "tg:{chat:user:1}:bucket:gpt": "budget",
        "tg:{chat:user:1}:day:2026-10-29": "budget",
        "tg:api:ip:1": "token bucket",
    }
    for key, kind in kinds.items():
        assert audit.kind_of(key, "tg") == kind, key


def test_finds_and_fixes_a_key_without_expiry(redis_client, prefix):
    algo = get_algorithm("token_bucket", redis_client, key_prefix=f"{prefix}:")
    algo.check("fine", 1, Limit(5, 1))
    redis_client.execute_command("SET", f"{prefix}:sw:leaked", "x")  # no TTL
    redis_client.execute_command("SET", f"{prefix}:{{rules}}", "x")  # exempt

    found = audit.audit(redis_client, prefix)
    assert found["sliding window"]["no_ttl"] == 1
    assert found["token bucket"]["no_ttl"] == 0
    assert found["live rules"]["no_ttl"] == 0
    assert redis_client.ttl(f"{prefix}:sw:leaked") == -1  # report does not change

    audit.audit(redis_client, prefix, fix=True, ttl=600)
    assert 0 < redis_client.ttl(f"{prefix}:sw:leaked") <= 600
    assert redis_client.ttl(f"{prefix}:{{rules}}") == -1  # still exempt
    assert "never expire" not in audit.render(audit.audit(redis_client, prefix), False)


def test_the_report_says_when_there_is_a_leak(redis_client, prefix):
    redis_client.execute_command("SET", f"{prefix}:sw:leaked", "x")
    text = audit.render(audit.audit(redis_client, prefix), fixed=False)
    assert "1 keys never expire" in text and "--fix" in text
