"""The publisher: computes a stats snapshot once a second and sends it to
every connected dashboard through the channel layer (Redis in production).

Computing it once here, not once per connection, keeps the load on Redis
constant however many people watch. Run it next to the web server:

    python manage.py tokenguard_feed
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from asgiref.sync import sync_to_async

from tokenguard.django.admin_api import ApiError
from tokenguard.django.admin_api import stats as build_stats

logger = logging.getLogger("tokenguard")

GROUP = "tokenguard.stats"


async def publish_once(layer: Any, **window: Any) -> dict[str, Any]:
    """Build one snapshot and send it to the group. Returns what was sent."""
    payload = await sync_to_async(build_stats, thread_sensitive=False)(**window)
    message = {"type": "stats", **payload}
    await layer.group_send(GROUP, {"type": "stats.message", "payload": message})
    return message


async def run_feed(
    layer: Any,
    interval: float = 1.0,
    stop: asyncio.Event | None = None,
    **window: Any,
) -> None:
    """Publish every `interval` seconds until `stop` is set. Survives errors."""
    stop = stop or asyncio.Event()
    failures = 0
    while not stop.is_set():
        started = time.monotonic()
        try:
            await publish_once(layer, **window)
            failures = 0
        except ApiError as exc:  # Redis hiccup: say so once in a while, keep going
            failures += 1
            if failures in (1, 10) or failures % 60 == 0:
                logger.warning(
                    "tokenguard feed: %s (%d in a row)", exc.message, failures
                )
        except Exception:
            failures += 1
            logger.exception("tokenguard feed: tick failed")
        delay = max(0.0, interval - (time.monotonic() - started))
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
