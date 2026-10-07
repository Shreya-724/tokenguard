from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def now(self) -> float: ...


class SystemClock:
    """Real clock. Monotonic, so unaffected by system time changes."""

    def now(self) -> float:
        return time.monotonic()


class FakeClock:
    """A clock you control manually. Tests use this instead of time.sleep."""

    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds

    def set(self, value: float) -> None:
        self._now = value