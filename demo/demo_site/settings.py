import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SECRET_KEY = "demo-only-not-a-secret"
DEBUG = True
ALLOWED_HOSTS: list[str] = []

INSTALLED_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "rest_framework",
]

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # After authentication, so request.user is available to key functions.
    "tokenguard.django.middleware.TokenGuardMiddleware",
]

ROOT_URLCONF = "demo_site.urls"
DATABASES = {
    "default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True

TOKENGUARD = {
    "REDIS_URL": os.getenv("REDIS_URL", "redis://localhost:6379/0"),
    "DEFAULT_RULE": {"capacity": 60, "refill_rate": 1},  # 60 burst, 1/sec sustained
    "FAIL_MODE": "open",  # if Redis dies, let traffic through (and log a warning)
    "KEY_PREFIX": "tg",
    "REDIS_TIMEOUT": 0.25,
    "TRUSTED_PROXIES": [],  # e.g. ["10.0.0.0/8"] when behind a load balancer
    "EXEMPT": [r"^/health/", r"^/static/", r"^/admin/"],
    "RULES": [
        {
            "name": "login",
            "match": r"^/login/",
            "capacity": 5,
            "refill_rate": 0.1,  # one new attempt every 10 seconds
            "key": "ip",
            "fail_mode": "closed",  # brute-force protection: never fail open
        },
        {
            "name": "chat-api",
            "match": r"^/api/summary/",
            "capacity": 30,
            "refill_rate": 2,
            "key": "user",
        },
    ],
}
