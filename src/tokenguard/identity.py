"""Bounding what a client can make us store.

A key function can return anything: an IP, a user id, or text taken from a
request header. Whatever it returns becomes part of a Redis key, so a client who
controls it controls how large that key is. `bound_identity` caps that.
"""

from __future__ import annotations

import hashlib

DEFAULT_MAX_KEY_LENGTH = 128
MIN_MAX_KEY_LENGTH = 16  # a hashed identity is 34 characters: "h:" plus 32 hex


def bound_identity(identity: str, max_length: int = DEFAULT_MAX_KEY_LENGTH) -> str:
    """The identity as-is if it fits, otherwise a fixed-size stand-in for it.

    The stand-in is "h:" plus the first 32 hex digits of the SHA-256 of the
    original, so the same long identity always lands in the same bucket (limiting
    still works) while its size in Redis is bounded.
    """
    if len(identity) <= max_length:
        return identity
    return "h:" + hashlib.sha256(identity.encode("utf-8", "replace")).hexdigest()[:32]
