"""Reads the TOKENGUARD dict from Django settings and applies defaults."""

from __future__ import annotations

import functools
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from tokenguard.algorithms import algorithm_names
from tokenguard.redis_client import create_client
from tokenguard.rulestore import RuleStore

DEFAULTS: dict[str, Any] = {
    "REDIS_URL": "redis://localhost:6379/0",
    "DEFAULT_RULE": {"capacity": 60, "refill_rate": 1},
    "FAIL_MODE": "open",  # "open" or "closed"; a rule can override it
    "ALGORITHM": "token_bucket",  # "token_bucket" or "fixed_window"; rules can override
    "KEY_PREFIX": "tg",
    "REDIS_TIMEOUT": 0.25,  # seconds, for connect and for each command
    "RULES": [],  # per-route overrides, first match wins
    "EXEMPT": [],  # regexes for paths that are never limited
    "TRUSTED_PROXIES": [],  # IPs/CIDRs allowed to set X-Forwarded-For
    "LIVE_RULES": False,  # True: rules can be changed live in Redis (see RuleStore)
    "LIVE_RULES_TTL": 5.0,  # seconds a process caches the live rules
    "ON_NEAR_LIMIT": None,  # callable(event) or dotted path, for budget alerts
}

FAIL_MODES = ("open", "closed")


def get_setting(name: str) -> Any:
    user_conf = getattr(settings, "TOKENGUARD", {}) or {}
    value = user_conf.get(name, DEFAULTS[name])
    if name == "FAIL_MODE":
        check_fail_mode(value)
    elif name == "ALGORITHM":
        check_algorithm(value)
    return value


def check_fail_mode(value: Any) -> None:
    if value not in FAIL_MODES:
        raise ImproperlyConfigured(
            f"TOKENGUARD fail mode must be one of {FAIL_MODES}, got {value!r}"
        )


def check_algorithm(value: Any) -> None:
    if value not in algorithm_names():
        raise ImproperlyConfigured(
            f"TOKENGUARD algorithm must be one of {algorithm_names()}, got {value!r}"
        )


@functools.lru_cache(maxsize=8)
def _client(url: str, timeout: float):
    return create_client(url, socket_timeout=timeout, socket_connect_timeout=timeout)


def get_client():
    """One pooled Redis client per (url, timeout), shared by every request."""
    return _client(get_setting("REDIS_URL"), float(get_setting("REDIS_TIMEOUT")))


@functools.lru_cache(maxsize=8)
def _rule_store(client, prefix: str, ttl: float) -> RuleStore:
    return RuleStore(client, key_prefix=prefix, ttl=ttl)


def get_rule_store() -> RuleStore:
    """The live-rules store for the current settings (one per process)."""
    return _rule_store(
        get_client(),
        f"{get_setting('KEY_PREFIX')}:",
        float(get_setting("LIVE_RULES_TTL")),
    )


def _mask(url: str) -> str:
    parts = urlsplit(url)
    if parts.password:
        netloc = f"{parts.username or ''}:***@{parts.hostname}"
        if parts.port:
            netloc += f":{parts.port}"
        parts = parts._replace(netloc=netloc)
    return urlunsplit(parts)


def effective_config() -> dict[str, Any]:
    """The settings tokenguard actually uses (password masked). Handy for debugging."""
    cfg = {name: get_setting(name) for name in DEFAULTS}
    cfg["REDIS_URL"] = _mask(cfg["REDIS_URL"])
    return cfg
