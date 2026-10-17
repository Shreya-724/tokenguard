"""Live rule changes: rule overrides kept in Redis and cached in each process.

    store = RuleStore(redis_client, key_prefix="tg:", ttl=5)
    store.set_rule("login", capacity=20, refill_rate=2)     # takes effect live
    store.snapshot().overrides["login"].capacity             # 20.0

An override changes a rule's `capacity`, `refill_rate` and/or `algorithm` without
a deploy. Every process asks Redis for the whole rule set at most once per `ttl`
seconds and serves requests from its cached copy in between, so a change reaches
every server within `ttl` seconds (the propagation delay) and a request never
waits on Redis for it. Each change bumps a version number that only goes up.

If Redis cannot be reached, the last known rules keep being served (or none, if
nothing was ever loaded), and it retries after another `ttl` seconds.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tokenguard.algorithms import algorithm_names
from tokenguard.errors import RedisUnavailableError, wrap_redis_errors

logger = logging.getLogger("tokenguard")

_HERE = Path(__file__).parent
_SET_LUA = (_HERE / "rules_set.lua").read_text(encoding="utf-8")
_DELETE_LUA = (_HERE / "rules_delete.lua").read_text(encoding="utf-8")
VERSION_FIELD = "__version__"


@dataclass(frozen=True)
class RuleOverride:
    """Replacement values for a rule. A field left as None keeps the original."""

    capacity: float | None = None
    refill_rate: float | None = None
    algorithm: str | None = None

    def to_json(self) -> str:
        data = {k: v for k, v in vars(self).items() if v is not None}
        return json.dumps(data, sort_keys=True)


@dataclass(frozen=True)
class RuleSet:
    """The rules as of one version."""

    version: int
    overrides: Mapping[str, RuleOverride] = field(default_factory=dict)
    loaded: bool = True  # False: Redis was never reachable, so these are not real


def _positive(name: str, value: Any) -> float:
    ok = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not ok or not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive number, got {value!r}")
    return float(value)


def validate_override(
    capacity: Any = None, refill_rate: Any = None, algorithm: Any = None
) -> RuleOverride:
    """Check the values and return an override, or raise ValueError."""
    if capacity is None and refill_rate is None and algorithm is None:
        raise ValueError("give at least one of capacity, refill_rate, algorithm")
    if algorithm is not None and algorithm not in algorithm_names():
        raise ValueError(
            f"unknown algorithm {algorithm!r}; choose one of {algorithm_names()}"
        )
    return RuleOverride(
        _positive("capacity", capacity) if capacity is not None else None,
        _positive("refill_rate", refill_rate) if refill_rate is not None else None,
        algorithm,
    )


def _parse(name: str, raw: str) -> RuleOverride | None:
    """One stored override, or None (logged) if it is damaged or invalid."""
    try:
        data = json.loads(raw)
        return validate_override(
            data.get("capacity"), data.get("refill_rate"), data.get("algorithm")
        )
    except (ValueError, AttributeError, TypeError) as exc:
        logger.warning("tokenguard: ignoring live rule %r (%s)", name, exc)
        return None


class RuleStore:
    """Live rule overrides in Redis, with a per-process cache."""

    def __init__(
        self,
        client: Any,
        key_prefix: str = "tb:",
        ttl: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl < 0:
            raise ValueError("ttl must be >= 0")
        self._r = client
        self._key = f"{key_prefix}{{rules}}"  # one hash; {} keeps it in one slot
        self.ttl = float(ttl)
        self.clock = clock  # tests replace it; production uses the monotonic clock
        self._set = client.register_script(_SET_LUA)
        self._delete = client.register_script(_DELETE_LUA)
        self._snap: RuleSet | None = None
        self._next_refresh = 0.0
        self._lock = threading.Lock()

    # ---- writing (the admin side) ----
    @wrap_redis_errors
    def set_rule(
        self,
        name: str,
        capacity: float | None = None,
        refill_rate: float | None = None,
        algorithm: str | None = None,
    ) -> int:
        """Replace the override for `name`. Returns the new rules version.

        `name` is the rule's scope: "default" for DEFAULT_RULE, the "name" of a
        RULES entry, or a decorated view's scope. Only the fields you give are
        overridden; the rest come from settings.
        """
        if not isinstance(name, str) or not name or name == VERSION_FIELD:
            raise ValueError(f"invalid rule name {name!r}")
        override = validate_override(capacity, refill_rate, algorithm)
        version = int(self._set(keys=[self._key], args=[name, override.to_json()]))
        self.invalidate()  # this process sees its own change straight away
        return version

    @wrap_redis_errors
    def delete_rule(self, name: str) -> int | None:
        """Remove the override for `name`. Returns the new version, or None."""
        version = int(self._delete(keys=[self._key], args=[name]))
        self.invalidate()
        return None if version < 0 else version

    # ---- reading (every request) ----
    def snapshot(self) -> RuleSet:
        """The rules, from the cache unless it is older than `ttl` seconds."""
        now = self.clock()
        snap = self._snap
        if snap is not None and now < self._next_refresh:
            return snap
        return self._reload(now)

    def get(self, name: str) -> RuleOverride | None:
        return self.snapshot().overrides.get(name)

    @property
    def version(self) -> int:
        return self.snapshot().version

    def refresh(self) -> RuleSet:
        """Ask Redis now, ignoring the cache."""
        return self._reload(self.clock(), block=True)

    def invalidate(self) -> None:
        """Forget the cache: the next read asks Redis."""
        self._next_refresh = 0.0

    @wrap_redis_errors
    def _read(self) -> dict[str, str]:
        return self._r.hgetall(self._key)

    def _reload(self, now: float, block: bool = False) -> RuleSet:
        # One thread reloads; the others keep using the cached copy meanwhile.
        if not self._lock.acquire(blocking=block):
            return self._snap or RuleSet(0, loaded=False)
        try:
            try:
                data = self._read()
            except RedisUnavailableError as exc:
                logger.warning("tokenguard: could not load live rules: %s", exc)
                self._next_refresh = now + self.ttl  # do not retry on every request
                if self._snap is None:
                    return RuleSet(0, loaded=False)
                return self._snap
            version = int(data.pop(VERSION_FIELD, 0))
            overrides = {}
            for name, raw in data.items():
                override = _parse(name, raw)
                if override is not None:
                    overrides[name] = override
            self._snap = RuleSet(version, overrides)
            self._next_refresh = now + self.ttl
            return self._snap
        finally:
            self._lock.release()
