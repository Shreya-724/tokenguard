"""The numbers a dashboard shows, in one JSON-ready dict.

    snapshot(reader, seconds=60)

is what `GET /tokenguard/stats/` returns and what the WebSocket feed pushes once
a second, so a page can draw itself from either.
"""

from __future__ import annotations

import time
from typing import Any

from tokenguard.metrics import MetricsReader, Summary


def snapshot(
    reader: MetricsReader,
    seconds: int = 60,
    step: int = 1,
    n: int = 5,
    minutes: int = 2,
) -> dict[str, Any]:
    """Everything one screen needs.

    seconds / step  the chart window and its bucket size (a point per `step`)
    n               how many consumers to list
    minutes         how far back the consumer and route lists look
    """
    points = reader.timeseries(seconds, step=step)
    summary = Summary(
        seconds=seconds,
        allowed=sum(p.allowed for p in points),
        blocked=sum(p.blocked for p in points),
        tokens=round(sum(p.tokens for p in points), 6),
    )
    by_tokens, by_blocked = reader.rankings(n=n, minutes=minutes)
    return {
        "ts": int(time.time()),
        "seconds": seconds,
        "step": step,
        "summary": summary.as_dict(),
        "series": [
            {"ts": p.ts, "allowed": p.allowed, "blocked": p.blocked, "tokens": p.tokens}
            for p in points
        ],
        "consumers": [c.as_dict() for c in by_tokens],
        "blocked_consumers": [c.as_dict() for c in by_blocked],
        "routes": [r.as_dict() for r in reader.routes(minutes)[:n]],
    }
