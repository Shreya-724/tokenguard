"""WebSocket live feed (Django Channels).

    ws://host/ws/tokenguard/stats/

Staff only: the connection is refused (HTTP 403) for anyone else, using the
session cookie. On connect the client gets a snapshot straight away, then a new
one every second while `manage.py tokenguard_feed` is running. Send
{"type": "ping"} to get {"type": "pong"}: handy for detecting a dead connection.
"""

from __future__ import annotations

import logging
from typing import Any

from asgiref.sync import sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from tokenguard.django.admin_api import ApiError
from tokenguard.django.admin_api import stats as build_stats
from tokenguard.django.feed import GROUP

logger = logging.getLogger("tokenguard")


def is_staff(user: Any) -> bool:
    return bool(user and user.is_authenticated and user.is_staff)


class StatsConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self) -> None:
        if not is_staff(self.scope.get("user")):
            await self.close()  # before accept: the client sees a 403
            return
        await self.channel_layer.group_add(GROUP, self.channel_name)
        await self.accept()
        try:  # a first picture straight away, not up to a second of blank
            payload = await sync_to_async(build_stats, thread_sensitive=False)()
        except ApiError as exc:
            await self.send_json({"type": "error", "error": exc.message})
        else:
            await self.send_json({"type": "stats", **payload})

    async def disconnect(self, code: int) -> None:
        await self.channel_layer.group_discard(GROUP, self.channel_name)

    async def receive_json(self, content: Any, **kwargs: Any) -> None:
        if isinstance(content, dict) and content.get("type") == "ping":
            await self.send_json({"type": "pong"})

    async def stats_message(self, event: dict[str, Any]) -> None:
        """Handles group messages of type "stats.message" from the feed."""
        await self.send_json(event["payload"])
