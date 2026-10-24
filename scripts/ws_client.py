"""Print the live stats feed in a terminal (a stand-in for the dashboard).

    python scripts/ws_client.py --login admin
    python scripts/ws_client.py --session <sessionid cookie value>
    python scripts/ws_client.py --login admin --count 5

Needs the server (daphne / runserver) and `manage.py tokenguard_feed` running,
and the `websockets` package (pip install websockets).

The feed is staff-only and uses the Django session cookie. --login NAME makes a
session for that staff user straight in the demo database (run from the repo
root, after `manage.py migrate` and `createsuperuser`), so no login page is
needed; --session takes the value of a `sessionid` cookie you already have.
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path


def make_session(username: str) -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "demo"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "demo_site.settings")
    import django

    django.setup()
    from django.contrib.auth import (
        BACKEND_SESSION_KEY,
        HASH_SESSION_KEY,
        SESSION_KEY,
        get_user_model,
    )
    from django.contrib.sessions.backends.db import SessionStore

    users = get_user_model().objects
    user = users.filter(username=username).first()
    if user is None:
        staff = list(users.filter(is_staff=True).values_list("username", flat=True))
        hint = (
            f"staff users here: {', '.join(staff)}"
            if staff
            else "there are no staff users yet; create one with:\n"
            f"    python demo/manage.py createsuperuser --username {username}"
        )
        sys.exit(f"no user named {username!r} in the demo database ({hint})")
    if not user.is_staff:
        sys.exit(f"{username!r} is not a staff user (is_staff must be true)")
    store = SessionStore()
    store[SESSION_KEY] = str(user.pk)
    store[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    store[HASH_SESSION_KEY] = user.get_session_auth_hash()
    store.save()
    return store.session_key


def describe(message: dict) -> str:
    if message.get("type") != "stats":
        return json.dumps(message)
    s = message["summary"]
    top = message["consumers"][0]["key"] if message["consumers"] else "-"
    last = message["series"][-1] if message["series"] else {}
    return (
        f"{time.strftime('%H:%M:%S')}  last 1s: {last.get('allowed', 0)} ok "
        f"{last.get('blocked', 0)} blocked | last {s['seconds']}s: "
        f"{s['requests']} requests, {s['blocked_ratio']:.0%} blocked | top: {top}"
    )


async def listen(url: str, session: str, count: int) -> None:
    import websockets

    headers = {
        "Cookie": f"sessionid={session}",
        # Channels refuses connections without an Origin that matches ALLOWED_HOSTS
        "Origin": "http://localhost:8000",
    }
    try:
        connection = websockets.connect(url, additional_headers=headers)
    except TypeError:  # older versions of the websockets package
        connection = websockets.connect(url, extra_headers=headers)
    async with connection as ws:
        print("connected; waiting for stats (Ctrl+C to stop)")
        seen = 0
        async for raw in ws:
            print(describe(json.loads(raw)))
            seen += 1
            if count and seen >= count:
                return


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--url", default="ws://localhost:8000/ws/tokenguard/stats/")
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--login", metavar="USERNAME")
    who.add_argument("--session", metavar="SESSIONID")
    parser.add_argument("--count", type=int, default=0, help="stop after N messages")
    args = parser.parse_args()
    session = args.session or make_session(args.login)
    try:
        asyncio.run(listen(args.url, session, args.count))
    except KeyboardInterrupt:
        pass
    except OSError as exc:
        print(f"could not connect: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # a refused handshake (403) shows up here
        print(f"connection failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
