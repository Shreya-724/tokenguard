"""Key functions: turn a request into the identity that gets its own bucket.

A key function takes a request and returns a string. Anonymous users fall back
to their IP address so they are never all lumped into one shared bucket.
"""

from __future__ import annotations

import hashlib
import ipaddress
from collections.abc import Callable
from typing import Any

from django.urls import Resolver404, resolve
from django.utils.module_loading import import_string

from tokenguard.django.conf import get_setting

KeyFunc = Callable[[Any], str]


def _parse_ip(value: str):
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def _is_trusted(addr, networks) -> bool:
    return addr is not None and any(addr in net for net in networks)


def client_ip(request) -> str:
    """The client's IP address.

    SECURITY: X-Forwarded-For is a plain header, so anyone can send a fake one.
    It is only believed when the direct peer (REMOTE_ADDR) is listed in
    TOKENGUARD["TRUSTED_PROXIES"]. We then walk the header from the right (the
    entry our own proxy appended) and return the first address that is not
    itself a trusted proxy. If TRUSTED_PROXIES is empty the header is ignored.
    """
    remote = request.META.get("REMOTE_ADDR", "") or "unknown"
    header = request.META.get("HTTP_X_FORWARDED_FOR")
    networks = [
        ipaddress.ip_network(p, strict=False) for p in get_setting("TRUSTED_PROXIES")
    ]
    if not header or not networks or not _is_trusted(_parse_ip(remote), networks):
        return remote

    hops = [h.strip() for h in header.split(",") if h.strip()]
    for hop in reversed(hops):
        addr = _parse_ip(hop)
        if addr is None:
            return remote  # garbage in the header: do not trust any of it
        if not _is_trusted(addr, networks):
            return str(addr)
    return hops[0] if _parse_ip(hops[0]) else remote  # every hop was a proxy


def ip(request) -> str:
    return f"ip:{client_ip(request)}"


def user(request) -> str:
    """Per authenticated user; anonymous users fall back to their IP."""
    u = getattr(request, "user", None)
    if u is not None and getattr(u, "is_authenticated", False):
        return f"user:{u.pk}"
    return ip(request)


def api_key(request, header: str = "HTTP_X_API_KEY") -> str:
    """Per API key (stored hashed, never raw); no key falls back to the IP."""
    raw = request.META.get(header)
    if not raw:
        return ip(request)
    return "apikey:" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def api_key_if(
    is_valid: Callable[[str], bool], header: str = "HTTP_X_API_KEY"
) -> KeyFunc:
    """A key function that only trusts API keys you recognise.

        key=api_key_if(lambda raw: ApiKey.objects.filter(hash=sha(raw)).exists())

    A recognised key gets its own bucket (stored hashed). A missing or unknown
    one is limited by IP address instead. With plain `api_key`, a client who
    sends a different made-up key on every request gets a fresh bucket each time
    and is never limited; here, made-up keys all land in the sender's IP bucket.

    `is_valid` runs on every request, so keep it cheap (a cache or a set lookup).
    """

    def key(request) -> str:
        raw = request.META.get(header)
        if raw and is_valid(raw):
            return "apikey:" + hashlib.sha256(raw.encode()).hexdigest()[:32]
        return ip(request)

    return key


def endpoint(request) -> str:
    """The URL pattern (e.g. /items/<int:pk>/), not the raw path.

    Using the raw path would give /items/1 and /items/2 separate buckets, and an
    attacker could invent endless paths. Unknown paths share one bucket.
    """
    try:
        route = resolve(request.path_info).route
    except Resolver404:
        return "unmatched"
    return route if route.startswith("/") else "/" + route


def combine(*funcs: KeyFunc) -> KeyFunc:
    """Join several key functions: combine(user, endpoint) -> 'user:42:/api/chat'."""

    def combined(request) -> str:
        return ":".join(f(request) for f in funcs)

    return combined


user_endpoint = combine(user, endpoint)
ip_endpoint = combine(ip, endpoint)

BUILTIN_KEYS: dict[str, KeyFunc] = {
    "user": user,
    "ip": ip,
    "api_key": api_key,
    "endpoint": endpoint,
    "user_endpoint": user_endpoint,
    "ip_endpoint": ip_endpoint,
}


def resolve_key(spec: str | KeyFunc | None) -> KeyFunc:
    """None -> user (IP fallback); a built-in name; a dotted path; or a callable."""
    if spec is None:
        return user
    if callable(spec):
        return spec
    if spec in BUILTIN_KEYS:
        return BUILTIN_KEYS[spec]
    return import_string(spec)
