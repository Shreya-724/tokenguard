"""The WebSocket live feed (Django Channels)."""

import asyncio
import uuid

import pytest

pytest.importorskip("django")
pytest.importorskip("channels.testing")
pytest.importorskip("pytest_asyncio")

from channels.layers import InMemoryChannelLayer, channel_layers  # noqa: E402
from channels.testing import WebsocketCommunicator  # noqa: E402
from django.contrib.auth.models import AnonymousUser, User  # noqa: E402

from tokenguard.django.consumers import StatsConsumer  # noqa: E402
from tokenguard.django.feed import publish_once, run_feed  # noqa: E402

URL = "/ws/tokenguard/stats/"
pytestmark = pytest.mark.asyncio


@pytest.fixture
def layer():
    """An in-memory channel layer, so these tests need no second Redis."""
    old = channel_layers.backends.get("default")
    channel_layers.backends["default"] = InMemoryChannelLayer()
    yield channel_layers.backends["default"]
    if old is None:
        channel_layers.backends.pop("default", None)
    else:
        channel_layers.backends["default"] = old


@pytest.fixture
def on(settings, redis_client, redis_url):
    prefix = f"tgws-{uuid.uuid4().hex[:8]}"
    settings.TOKENGUARD = {
        "REDIS_URL": redis_url,
        "KEY_PREFIX": prefix,
        "METRICS": True,
    }
    yield
    for k in redis_client.scan_iter(f"{prefix}:*"):
        redis_client.delete(k)


def socket(user):
    communicator = WebsocketCommunicator(StatsConsumer.as_asgi(), URL)
    communicator.scope["user"] = user
    return communicator


def staff():
    return User(username="boss", is_staff=True)


# ---- who may connect ----
async def test_anonymous_visitors_are_refused(layer, on):
    connected, _ = await socket(AnonymousUser()).connect()
    assert not connected


async def test_signed_in_non_staff_are_refused(layer, on):
    connected, _ = await socket(User(username="x", is_staff=False)).connect()
    assert not connected


async def test_a_missing_user_is_refused(layer, on):
    communicator = WebsocketCommunicator(StatsConsumer.as_asgi(), URL)
    connected, _ = await communicator.connect()
    assert not connected


# ---- what staff receive ----
async def test_staff_get_a_snapshot_straight_away(layer, on):
    communicator = socket(staff())
    connected, _ = await communicator.connect()
    assert connected
    first = await communicator.receive_json_from(timeout=5)
    assert first["type"] == "stats" and "summary" in first and "series" in first
    await communicator.disconnect()


async def test_published_snapshots_reach_connected_staff(layer, on):
    communicator = socket(staff())
    await communicator.connect()
    await communicator.receive_json_from(timeout=5)  # the first one
    await publish_once(layer, seconds=10)
    message = await communicator.receive_json_from(timeout=5)
    assert message["type"] == "stats" and len(message["series"]) == 10
    await communicator.disconnect()


async def test_every_connection_gets_every_snapshot(layer, on):
    a, b = socket(staff()), socket(staff())
    await a.connect()
    await b.connect()
    await a.receive_json_from(timeout=5)
    await b.receive_json_from(timeout=5)
    await publish_once(layer, seconds=5)
    assert (await a.receive_json_from(timeout=5))["type"] == "stats"
    assert (await b.receive_json_from(timeout=5))["type"] == "stats"
    await a.disconnect()
    await b.disconnect()


async def test_ping_gets_a_pong(layer, on):
    communicator = socket(staff())
    await communicator.connect()
    await communicator.receive_json_from(timeout=5)
    await communicator.send_json_to({"type": "ping"})
    assert await communicator.receive_json_from(timeout=5) == {"type": "pong"}
    await communicator.disconnect()


async def test_other_messages_are_ignored(layer, on):
    communicator = socket(staff())
    await communicator.connect()
    await communicator.receive_json_from(timeout=5)
    await communicator.send_json_to({"type": "give-me-everything"})
    await communicator.send_json_to("garbage")
    assert await communicator.receive_nothing(timeout=0.3)
    await communicator.disconnect()


async def test_publishing_after_everyone_left_is_fine(layer, on):
    communicator = socket(staff())
    await communicator.connect()
    await communicator.receive_json_from(timeout=5)
    await communicator.disconnect()
    await publish_once(layer, seconds=5)  # nobody listening: no error


# ---- the feed loop ----
async def test_the_feed_publishes_repeatedly_and_stops(layer, on):
    communicator = socket(staff())
    await communicator.connect()
    await communicator.receive_json_from(timeout=5)
    stop = asyncio.Event()
    task = asyncio.create_task(run_feed(layer, interval=0.05, stop=stop, seconds=5))
    for _ in range(3):
        assert (await communicator.receive_json_from(timeout=5))["type"] == "stats"
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    await communicator.disconnect()


async def test_the_feed_survives_a_failing_tick(layer, on):
    stop = asyncio.Event()
    # seconds=0 is rejected every tick; the loop must keep going, not crash
    task = asyncio.create_task(run_feed(layer, interval=0.02, stop=stop, seconds=0))
    await asyncio.sleep(0.2)
    assert not task.done()
    stop.set()
    await asyncio.wait_for(task, timeout=5)
