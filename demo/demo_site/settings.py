import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "demo-only-not-a-secret"
DEBUG = True
ALLOWED_HOSTS: list[str] = []

# Read from the environment, so `manage.py` works without the tests package.
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

INSTALLED_APPS = [
    "daphne",  # first: makes runserver speak ASGI (needed for the WebSocket)
    "channels",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
    "tokenguard.django",  # adds `manage.py tokenguard_feed`
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # After authentication, so request.user is available to key functions.
    "tokenguard.django.middleware.TokenGuardMiddleware",
]

ROOT_URLCONF = "demo_site.urls"
ASGI_APPLICATION = "demo_site.asgi.application"
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [REDIS_URL]},
    }
}
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}
# The React dev server (Vite) is a different origin from Django, and Django's CSRF
# check compares the browser's Origin header with the host it sees. Trust the dev
# server's origin so signing in and changing rules works from the dashboard.
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

TOKENGUARD = {
    "REDIS_URL": REDIS_URL,
    "DEFAULT_RULE": {"capacity": 60, "refill_rate": 1},  # 60 burst, 1/sec sustained
    "FAIL_MODE": "open",  # if Redis dies, let traffic through (and log a warning)
    "KEY_PREFIX": "tg",
    "REDIS_TIMEOUT": 0.25,
    "TRUSTED_PROXIES": [],  # e.g. ["10.0.0.0/8"] when behind a load balancer
    "EXEMPT": [r"^/health/", r"^/static/", r"^/admin/"],
    "LIVE_RULES": True,  # Week 5: change limits without a redeploy
    "LIVE_RULES_TTL": 2,
    "METRICS": True,  # Week 6: record every decision for the dashboard
    "RULES": [
        {
            "name": "dashboard-login",
            "match": r"^/tokenguard/login/",
            "capacity": 5,
            "refill_rate": 0.1,  # one new attempt every 10 seconds
            "key": "ip",
            "fail_mode": "closed",  # never let password guessing through
        },
        {
            "name": "login",
            "match": r"^/login/",
            "capacity": 5,
            "refill_rate": 0.1,  # one new attempt every 10 seconds
            "key": "ip",
            "fail_mode": "closed",  # brute-force protection: never fail open
        },
    ],
}
