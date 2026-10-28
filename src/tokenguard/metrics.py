"""Metrics: record every limiter decision in Redis, and read them back.

    recorder = MetricsRecorder(client)
    recorder.record("chat", "user:42", allowed=True, tokens=350)

    reader = MetricsReader(client)
    reader.summary(seconds=60)          # requests, blocked ratio, requests/sec
    reader.timeseries(seconds=300)      # one point per second, for a chart
    reader.top_consumers(n=5)           # who is using the most right now
    reader.bucket_level("chat", "user:42", Limit(60, 1))   # what is left

What is stored (all in Redis, nothing in process memory):

* One hash per minute, `<prefix>metrics:<minute>`: per-second counters
  (`<sec>:a` allowed, `<sec>:b` blocked, `<sec>:t` tokens) and per-rule counters
  for the minute (`r:<scope>:a|b|t`).
* Two sorted sets per minute: `<prefix>metrics:top:<minute>` (tokens spent, per
  consumer) and `<prefix>metrics:blk:<minute>` (blocked requests, per consumer).
* Every key expires after `retention` seconds, so old data cleans itself up.

Cost: one Lua call (one round trip) per decision, and nothing here ever raises
into a request: if Redis is slow or down, the sample is dropped and counted in
`recorder.dropped`.

Buffered mode (`flush_interval > 0`) takes that round trip off the request path.
Samples wait in a bounded in-process queue; a background thread merges the ones
for the same second and consumer, and sends them all in one pipelined round trip
every `flush_interval` seconds. The numbers show up in Redis up to that long
later, and samples still queued when a process is killed (not stopped) are lost.

Limits worth knowing:

* "tokens" are the cost units the rule charges (1 per request for a plain
  rate limit; raw model tokens for LLM routes, corrected after reconcile).
* Each minute keeps at most `max_consumers` consumers per sorted set. When it is
  full the smallest is dropped, so heavy users always survive but a long tail of
  one-off keys may be missing. A top-N list is not affected by that.
* Timestamps come from the application server's clock, not Redis's.
"""

from __future__ import annotations

import atexit
import collections
import logging
import math
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import redis

from tokenguard.algorithms import Limit, get_algorithm
from tokenguard.clock import Clock, WallClock

logger = logging.getLogger("tokenguard")

_RECORD_LUA = (Path(__file__).parent / "metrics_record.lua").read_text(encoding="utf-8")
_SEP = "\x1f"  # between scope and identity inside a sorted-set member

DEFAULT_RETENTION = 3600  # seconds of history kept
DEFAULT_MAX_CONSUMERS = 1000  # per minute, per sorted set
DEFAULT_MAX_PENDING = 10_000  # buffered mode: samples held before dropping


def _member(scope: str, identity: str) -> str:
    return f"{scope}{_SEP}{identity}"


@dataclass(frozen=True)
class Point:
    """One time bucket of the chart: `ts` is its start, a unix time in seconds."""

    ts: int
    allowed: int
    blocked: int
    tokens: float

    @property
    def requests(self) -> int:
        return self.allowed + self.blocked


@dataclass(frozen=True)
class Summary:
    seconds: int  # the window the numbers cover
    allowed: int
    blocked: int
    tokens: float

    @property
    def requests(self) -> int:
        return self.allowed + self.blocked

    @property
    def blocked_ratio(self) -> float:
        return self.blocked / self.requests if self.requests else 0.0

    @property
    def requests_per_second(self) -> float:
        return self.requests / self.seconds if self.seconds else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "seconds": self.seconds,
            "allowed": self.allowed,
            "blocked": self.blocked,
            "requests": self.requests,
            "tokens": self.tokens,
            "blocked_ratio": round(self.blocked_ratio, 4),
            "requests_per_second": round(self.requests_per_second, 3),
        }


@dataclass(frozen=True)
class Consumer:
    scope: str
    identity: str
    tokens: float
    blocked: int

    @property
    def key(self) -> str:
        """The bucket key: what the limiter itself uses (scope:identity)."""
        return f"{self.scope}:{self.identity}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "scope": self.scope,
            "identity": self.identity,
            "tokens": self.tokens,
            "blocked": self.blocked,
        }


@dataclass(frozen=True)
class RouteStats:
    scope: str
    allowed: int
    blocked: int
    tokens: float

    @property
    def requests(self) -> int:
        return self.allowed + self.blocked

    @property
    def blocked_ratio(self) -> float:
        return self.blocked / self.requests if self.requests else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "allowed": self.allowed,
            "blocked": self.blocked,
            "requests": self.requests,
            "tokens": self.tokens,
            "blocked_ratio": round(self.blocked_ratio, 4),
        }


@dataclass(frozen=True)
class BucketLevel:
    key: str
    algorithm: str
    capacity: float
    remaining: float
    reset_after: float | None  # seconds until full again; None if unknown

    @property
    def used(self) -> float:
        return self.capacity - self.remaining

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "algorithm": self.algorithm,
            "capacity": self.capacity,
            "remaining": self.remaining,
            "used": self.used,
            "reset_after": self.reset_after,
        }


class MetricsRecorder:
    """Writes metrics. Safe to call from a request: it never raises."""

    def __init__(
        self,
        client: Any,
        key_prefix: str = "tg:",
        retention: int = DEFAULT_RETENTION,
        max_consumers: int = DEFAULT_MAX_CONSUMERS,
        clock: Clock | None = None,
        flush_interval: float = 0.0,
        max_pending: int = DEFAULT_MAX_PENDING,
    ) -> None:
        if retention < 60:
            raise ValueError("retention must be at least 60 seconds")
        if max_consumers < 1:
            raise ValueError("max_consumers must be at least 1")
        if flush_interval < 0:
            raise ValueError("flush_interval must be 0 (off) or more")
        if max_pending < 1:
            raise ValueError("max_pending must be at least 1")
        self._client = client
        self._interval = float(flush_interval)
        self._max_pending = int(max_pending)
        self._pending: collections.deque[tuple[Any, ...]] = collections.deque()
        self._thread: threading.Thread | None = None
        self._pid = os.getpid()
        self._stop = threading.Event()
        self._start_lock = threading.Lock()
        self._prefix = key_prefix
        self._retention = int(retention)
        self._max = int(max_consumers)
        self._clock = clock or WallClock()
        self._script = client.register_script(_RECORD_LUA)
        self.dropped = 0  # samples lost because Redis failed

    def record(
        self, scope: str, identity: str, *, allowed: bool, tokens: float = 0.0
    ) -> None:
        """One decision. `tokens` only counts when the request was allowed."""
        spent = tokens if allowed else 0.0
        self._write(scope, identity, int(allowed), int(not allowed), spent)

    def record_adjust(self, scope: str, identity: str, tokens: float) -> None:
        """Correct the tokens of an earlier decision (actual minus estimate)."""
        if tokens:
            self._write(scope, identity, 0, 0, tokens)

    def _keys(self, minute: int) -> list[str]:
        return [
            f"{self._prefix}metrics:{minute}",
            f"{self._prefix}metrics:top:{minute}",
            f"{self._prefix}metrics:blk:{minute}",
        ]

    def _args(
        self,
        sec: int,
        scope: str,
        member: str,
        allowed: int,
        blocked: int,
        tokens: float,
    ) -> list[Any]:
        return [
            sec,
            scope,
            member,
            allowed,
            blocked,
            repr(float(tokens)) if tokens else 0,
            self._retention + 120,
            self._max,
        ]

    def _write(
        self, scope: str, identity: str, allowed: int, blocked: int, tokens: float
    ) -> None:
        now = self._clock.now()
        member = _member(scope, identity)
        if self._interval:
            self._enqueue(
                (int(now // 60), int(now % 60), scope, member, allowed, blocked, tokens)
            )
            return
        try:
            self._script(
                keys=self._keys(int(now // 60)),
                args=self._args(int(now % 60), scope, member, allowed, blocked, tokens),
            )
        except (redis.RedisError, OSError) as exc:
            self.dropped += 1
            logger.warning("tokenguard: metrics sample dropped: %s", exc)

    # -- buffered mode -----------------------------------------------------

    @property
    def pending(self) -> int:
        """Samples waiting to be sent (always 0 when not buffered)."""
        return len(self._pending)

    def _enqueue(self, sample: tuple[Any, ...]) -> None:
        self._ensure_thread()
        if len(self._pending) >= self._max_pending:
            self.dropped += 1  # Redis is slower than traffic: shed, never block
            return
        self._pending.append(sample)

    def _ensure_thread(self) -> None:
        thread = self._thread
        if thread is not None and thread.is_alive() and self._pid == os.getpid():
            return
        with self._start_lock:
            if self._pid != os.getpid():  # forked: the parent's queue is not ours
                self._pending.clear()
                self._pid = os.getpid()
                self._thread = None
            if self._thread is None or not self._thread.is_alive():
                self._stop = threading.Event()
                self._thread = threading.Thread(
                    target=self._loop,
                    args=(self._stop,),
                    name="tokenguard-metrics",
                    daemon=True,
                )
                self._thread.start()
                atexit.register(self.close)

    def _loop(self, stop: threading.Event) -> None:
        while not stop.wait(self._interval):
            self.flush()
        self.flush()

    def flush(self) -> int:
        """Send everything queued, in one round trip. Never raises.

        Returns how many samples were sent. Samples for the same second and
        consumer are merged first, so a busy caller costs one Lua call per
        flush, not one per request.
        """
        batch = []
        while True:
            try:
                batch.append(self._pending.popleft())
            except IndexError:
                break
        if not batch:
            return 0
        merged: dict[tuple[Any, ...], list[float]] = {}
        for minute, sec, scope, member, allowed, blocked, tokens in batch:
            slot = merged.setdefault((minute, sec, scope, member), [0, 0, 0.0])
            slot[0] += allowed
            slot[1] += blocked
            slot[2] += tokens
        try:
            pipe = self._client.pipeline(transaction=False)
            for (minute, sec, scope, member), (a, b, t) in merged.items():
                self._script(
                    keys=self._keys(minute),
                    args=self._args(sec, scope, member, int(a), int(b), t),
                    client=pipe,
                )
            pipe.execute()
        except (redis.RedisError, OSError) as exc:
            self.dropped += len(batch)
            logger.warning(
                "tokenguard: %d metrics samples dropped: %s", len(batch), exc
            )
            return 0
        return len(batch)

    def close(self) -> None:
        """Stop the background thread and send what is left. Safe to repeat."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
        self.flush()


class MetricsReader:
    """Reads metrics back. Raises the Redis error if Redis is unreachable."""

    def __init__(
        self,
        client: Any,
        key_prefix: str = "tg:",
        retention: int = DEFAULT_RETENTION,
        clock: Clock | None = None,
    ) -> None:
        self._r = client
        self._prefix = key_prefix
        self._retention = int(retention)
        self._clock = clock or WallClock()

    # -- internals ----------------------------------------------------------
    def _minutes(self, seconds: int) -> tuple[int, list[int]]:
        """(now as whole seconds, the minute buckets that cover the window)."""
        now = int(self._clock.now())
        first = (now - seconds + 1) // 60
        return now, list(range(first, now // 60 + 1))

    def _hashes(self, minutes: list[int]) -> list[dict[str, str]]:
        pipe = self._r.pipeline(transaction=False)
        for m in minutes:
            pipe.hgetall(f"{self._prefix}metrics:{m}")
        return pipe.execute()

    @staticmethod
    def _check_window(value: float, name: str, maximum: float) -> int:
        n = int(value)
        if n < 1:
            raise ValueError(f"{name} must be at least 1")
        return min(n, int(maximum))

    # -- time series --------------------------------------------------------
    def timeseries(self, seconds: int = 300, step: int = 1) -> list[Point]:
        """Allowed/blocked/tokens over the last `seconds`, oldest first.

        `step` groups seconds into wider buckets (step=60 gives per-minute
        points). Empty seconds are filled with zeros so a chart has no gaps.
        """
        seconds = self._check_window(seconds, "seconds", self._retention)
        step = self._check_window(step, "step", seconds)
        now, minutes = self._minutes(seconds)
        start = now - seconds + 1
        cells: dict[int, list[float]] = {}  # second -> [allowed, blocked, tokens]
        for minute, data in zip(minutes, self._hashes(minutes), strict=True):
            for field, value in data.items():
                sec, _, kind = field.partition(":")
                if not sec.isdigit() or kind not in ("a", "b", "t"):
                    continue  # a per-rule field
                ts = minute * 60 + int(sec)
                if ts < start or ts > now:
                    continue
                cell = cells.setdefault(ts, [0, 0, 0.0])
                cell[("a", "b", "t").index(kind)] = float(value)
        points = []
        for bucket_start in range(start, now + 1, step):
            a = b = 0
            t = 0.0
            for ts in range(bucket_start, min(bucket_start + step, now + 1)):
                cell = cells.get(ts)
                if cell:
                    a += int(cell[0])
                    b += int(cell[1])
                    t += cell[2]
            points.append(Point(bucket_start, a, b, round(t, 6)))
        return points

    def summary(self, seconds: int = 60) -> Summary:
        """Totals over the last `seconds`."""
        seconds = self._check_window(seconds, "seconds", self._retention)
        points = self.timeseries(seconds, step=seconds)
        p = points[0]
        return Summary(seconds, p.allowed, p.blocked, p.tokens)

    # -- who and where ------------------------------------------------------
    def top_consumers(
        self, n: int = 10, minutes: int = 5, by: str = "tokens"
    ) -> list[Consumer]:
        """The heaviest consumers over the last `minutes` (whole-minute buckets).

        `by` is "tokens" (most spent) or "blocked" (most often turned away).
        """
        if by not in ("tokens", "blocked"):
            raise ValueError('by must be "tokens" or "blocked"')
        return self._ranked(self._consumer_totals(minutes), n, by)

    def rankings(
        self, n: int = 10, minutes: int = 5
    ) -> tuple[list[Consumer], list[Consumer]]:
        """(top by tokens, top by blocked) from one Redis round trip."""
        totals = self._consumer_totals(minutes)
        return self._ranked(totals, n, "tokens"), self._ranked(totals, n, "blocked")

    def _consumer_totals(self, minutes: int) -> dict[str, list[float]]:
        minutes = self._check_window(minutes, "minutes", self._retention // 60 + 1)
        now = int(self._clock.now())
        pipe = self._r.pipeline(transaction=False)
        for m in range(now // 60 - minutes + 1, now // 60 + 1):
            pipe.zrange(f"{self._prefix}metrics:top:{m}", 0, -1, withscores=True)
            pipe.zrange(f"{self._prefix}metrics:blk:{m}", 0, -1, withscores=True)
        totals: dict[str, list[float]] = {}
        for i, rows in enumerate(pipe.execute()):
            slot = i % 2  # 0 = tokens, 1 = blocked
            for member, score in rows:
                totals.setdefault(member, [0.0, 0.0])[slot] += float(score)
        return totals

    @staticmethod
    def _ranked(totals: dict[str, list[float]], n: int, by: str) -> list[Consumer]:
        order = 0 if by == "tokens" else 1
        ranked = sorted(totals.items(), key=lambda kv: kv[1][order], reverse=True)
        out = []
        for member, (tokens, blocked) in ranked:
            if (tokens if by == "tokens" else blocked) <= 0:
                continue  # fully refunded, or never blocked
            scope, _, identity = member.partition(_SEP)
            out.append(Consumer(scope, identity, round(tokens, 6), int(blocked)))
            if len(out) >= n:
                break
        return out

    def routes(self, minutes: int = 5) -> list[RouteStats]:
        """Per-rule totals over the last `minutes`, busiest first."""
        minutes = self._check_window(minutes, "minutes", self._retention // 60 + 1)
        now = int(self._clock.now())
        buckets = list(range(now // 60 - minutes + 1, now // 60 + 1))
        totals: dict[str, list[float]] = {}
        for data in self._hashes(buckets):
            for field, value in data.items():
                if not field.startswith("r:"):
                    continue
                scope, _, kind = field[2:].rpartition(":")
                if kind in ("a", "b", "t"):
                    cell = totals.setdefault(scope, [0, 0, 0.0])
                    cell[("a", "b", "t").index(kind)] += float(value)
        stats = [
            RouteStats(scope, int(a), int(b), round(t, 6))
            for scope, (a, b, t) in totals.items()
        ]
        return sorted(stats, key=lambda s: s.requests, reverse=True)

    # -- one key's bucket right now ----------------------------------------
    def bucket_level(
        self,
        scope: str,
        identity: str,
        limit: Limit,
        algorithm: str = "token_bucket",
        key_prefix: str | None = None,
    ) -> BucketLevel:
        """How much of `limit` this consumer has left, without spending anything.

        `key_prefix` is the limiter's own prefix (the KEY_PREFIX setting plus a
        colon); it defaults to the one this reader was built with.
        """
        algo = get_algorithm(algorithm, self._r, key_prefix=key_prefix or self._prefix)
        key = f"{scope}:{identity}"
        decision = algo.peek(key, 0, limit)
        reset = decision.reset_after
        if reset is None and limit.refill_rate > 0:
            reset = max(0.0, limit.capacity - decision.remaining) / limit.refill_rate
        if reset is not None and not math.isfinite(reset):
            reset = None
        return BucketLevel(key, algorithm, limit.capacity, decision.remaining, reset)
