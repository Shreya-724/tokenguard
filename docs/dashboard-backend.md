# Dashboard backend: REST API and live feed

Everything the dashboard needs from the server, staff-only:

| | |
|---|---|
| `GET /tokenguard/stats/?seconds=60&step=1&n=5&minutes=2` | the snapshot: summary, a chart series, top consumers, most blocked, per-rule totals |
| `GET /tokenguard/consumers/?n=10&minutes=5&by=tokens\|blocked` | who is using the most / is turned away the most |
| `GET /tokenguard/buckets/<scope>:<id>/` | what one key has left, without spending it |
| `GET /tokenguard/rules/` | every rule: configured, live override, effective |
| `PUT /tokenguard/rules/<scope>/` | change a rule live: `{"capacity": 100, "refill_rate": 5, "algorithm": "sliding_window"}` |
| `DELETE /tokenguard/rules/<scope>/` | put a rule back to what the settings say |
| `ws://host/ws/tokenguard/stats/` | the same snapshot pushed every second |

Errors are JSON `{"error": "..."}`: 400 bad input, 403 not staff, 404 unknown
rule or key, 422 bucket of a budgeted rule (not available yet), 503 Redis down.

## Who can use it

Only users with `is_staff`. The REST views accept a logged-in session or HTTP
Basic (use HTTPS). The WebSocket uses the session cookie and is refused (403)
for everyone else, and Channels checks the `Origin` against `ALLOWED_HOSTS`.
The REST views are exempt from rate limiting, so polling never eats a limit.

Changing a rule writes to the same store as `scripts/tokenguard_rules.py`:
servers apply it within `LIVE_RULES_TTL` seconds and need `"LIVE_RULES": True`.
The rules response says whether that is on, and shows an override even when it
is not applied.

## Setup

```
pip install -e ".[dashboard]"        # DRF, Channels, channels-redis, daphne
```

`settings.py`:

```python
INSTALLED_APPS = [
    "daphne",                  # first: makes runserver speak ASGI
    "channels",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "tokenguard.django",       # adds `manage.py tokenguard_feed`
]
ASGI_APPLICATION = "demo_site.asgi.application"
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}
TOKENGUARD = {..., "METRICS": True, "LIVE_RULES": True}
```

`urls.py`: `path("tokenguard/", include("tokenguard.django.api_urls"))`.
`asgi.py`: route WebSockets to `tokenguard.django.routing.websocket_urlpatterns`
(see `demo/demo_site/asgi.py`).

Run three things:

```
python demo/manage.py runserver           # the web server (ASGI, via daphne)
python demo/manage.py tokenguard_feed     # publishes a snapshot every second
python scripts/ws_client.py --login admin # watch it
```

## How the live feed works

`tokenguard_feed` computes **one** snapshot per second and sends it to the
channel layer group `tokenguard.stats`; every connected dashboard receives it.
So Redis does the same work whether one person watches or fifty. A new
connection also gets an immediate snapshot, so a page is never blank for a
second. Send `{"type": "ping"}` and the server answers `{"type": "pong"}`.

Without the feed process the socket still connects and shows the first
snapshot, but does not update.

## Limits

- Bucket levels for rules with a budget are not available yet (422).
- Top consumers and routes are per whole minute (see docs/metrics.md).
- No login page is included; use the Django admin login or `ws_client.py --login`.
