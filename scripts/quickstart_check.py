"""Run the README quick start for real, as a stranger would, and check the result.

    python scripts/quickstart_check.py --redis redis://localhost:6379/5

Needs Django and tokenguard installed in the interpreter that runs it, and a Redis.
It creates a new Django project in a temporary folder, makes exactly the edits the
README's steps 3 and 4 describe, starts the server, sends seven requests to /ping/
and expects five 200s then 429s, with the documented headers on the refusal.
`release_check.py install` runs it inside the fresh virtualenv it builds.
"""

import argparse
import json
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import redis

AUTH_LINE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<q>['\"])django\.contrib\.auth\.middleware"
    r"\.AuthenticationMiddleware(?P=q),[ \t\r]*$",
    re.MULTILINE,
)
MIDDLEWARE = '"tokenguard.django.middleware.TokenGuardMiddleware",'

SETTINGS = """
TOKENGUARD = {
    "REDIS_URL": "__REDIS__",
    "DEFAULT_RULE": {"capacity": 60, "refill_rate": 1},
    "FAIL_MODE": "open",
    "KEY_PREFIX": "__PREFIX__",
}
"""

URLS = """from django.http import JsonResponse
from django.urls import path
from tokenguard.django import rate_limit


@rate_limit(capacity=5, refill_rate=0.1, key="ip")   # burst of 5, then one every 10 s
def ping(request):
    return JsonResponse({"ok": True})


urlpatterns = [path("ping/", ping)]
"""


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def get(url):
    """(status, headers, body) without raising on 4xx."""
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read()


def patch_settings(text, redis_url, prefix):
    """The edits the README's step 3 asks for, applied to a settings.py text."""
    match = AUTH_LINE.search(text)
    if match is None:
        raise SystemExit(
            "this Django's default settings have no AuthenticationMiddleware"
        )
    quote, indent = match.group("q"), match.group("indent")
    line = MIDDLEWARE.replace('"', quote)
    text = text[: match.end()] + f"\n{indent}{line}" + text[match.end() :]
    return text + SETTINGS.replace("__REDIS__", redis_url).replace("__PREFIX__", prefix)


def build_project(root, redis_url, prefix):
    subprocess.run(
        [sys.executable, "-m", "django", "startproject", "mysite"], cwd=root, check=True
    )
    project = Path(root) / "mysite"
    settings = project / "mysite" / "settings.py"
    text = patch_settings(settings.read_text("utf-8"), redis_url, prefix)
    settings.write_text(text, "utf-8")
    (project / "mysite" / "urls.py").write_text(URLS, "utf-8")
    return project


def run_check(redis_url):
    problems = []
    prefix = f"qs{uuid.uuid4().hex[:8]}"
    with tempfile.TemporaryDirectory() as root:
        project = build_project(root, redis_url, prefix)
        port = free_port()
        server = subprocess.Popen(
            [sys.executable, "manage.py", "runserver", str(port), "--noreload"],
            cwd=project,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        url = f"http://127.0.0.1:{port}/ping/"
        try:
            for _ in range(60):
                try:
                    urllib.request.urlopen(url, timeout=2)
                    break
                except urllib.error.HTTPError:
                    break
                except OSError:
                    time.sleep(0.5)
            else:
                problems.append("the development server did not start")
                return problems
            # the probe above spent one token, so start a fresh bucket
            client = redis.Redis.from_url(redis_url)
            for key in client.scan_iter(f"{prefix}:*"):
                client.delete(key)
            seen = [get(url) for _ in range(7)]
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
            client = redis.Redis.from_url(redis_url)
            for key in client.scan_iter(f"{prefix}:*"):
                client.delete(key)
    codes = [status for status, _, _ in seen]
    print("status codes:", codes)
    if codes != [200] * 5 + [429] * 2:
        problems.append(f"expected five 200s then two 429s, got {codes}")
        return problems
    _, headers, body = seen[-1]
    if headers.get("X-RateLimit-Limit") != "5":
        problems.append(f"X-RateLimit-Limit was {headers.get('X-RateLimit-Limit')!r}")
    if headers.get("X-RateLimit-Remaining") != "0":
        problems.append("X-RateLimit-Remaining was not 0 on the refusal")
    if not headers.get("Retry-After", "").isdigit():
        problems.append(f"Retry-After was {headers.get('Retry-After')!r}")
    try:
        payload = json.loads(body)
    except ValueError:
        payload = {}
    if payload.get("error") != "rate_limited":
        problems.append(f"the 429 body was {body[:80]!r}")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--redis", default="redis://localhost:6379/5")
    args = parser.parse_args(argv)
    redis.Redis.from_url(args.redis).ping()
    problems = run_check(args.redis)
    if problems:
        print("QUICK START CHECK FAILED:")
        for problem in problems:
            print("  -", problem)
        return 1
    print(
        "the README quick start works: five 200s, then 429 with the documented headers"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
