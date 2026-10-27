"""Settings for load tests (Week 7). Never use these in production.

    BENCH_MODE=baseline   the /bench/ views have no rate limit at all
    BENCH_MODE=limited    the /bench/ views run behind tokenguard (default)

    BENCH_METRICS=0       turn off dashboard metrics (one fewer Redis call)
    BENCH_LIVE_RULES=0    turn off live rule overrides

Everything else comes from demo_site.settings, so the two modes differ in
exactly one thing. The middleware is removed: the /bench/ views use the
decorator, and a second limiter in front would be measured as well.
"""

import os

from .settings import *  # noqa: F403
from .settings import MIDDLEWARE, TOKENGUARD

BENCH_MODE = os.getenv("BENCH_MODE", "limited")
if BENCH_MODE not in ("baseline", "limited"):
    raise RuntimeError("BENCH_MODE must be 'baseline' or 'limited'")

DEBUG = False
ALLOWED_HOSTS = ["*"]
REDIS_URL = os.getenv("BENCH_REDIS_URL", "redis://localhost:6379/5")  # db 5: throwaway

MIDDLEWARE = [m for m in MIDDLEWARE if "TokenGuardMiddleware" not in m]
LOGGING = {  # per-request log lines would be measured too
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"null": {"class": "logging.NullHandler"}},
    "root": {"handlers": ["null"], "level": "ERROR"},
}

TOKENGUARD = {
    **TOKENGUARD,
    "REDIS_URL": REDIS_URL,
    "METRICS": os.getenv("BENCH_METRICS", "1") == "1",
    "LIVE_RULES": os.getenv("BENCH_LIVE_RULES", "1") == "1",
    "KEY_PREFIX": "bench",
    "FAIL_MODE": "closed",  # a Redis failure must show up as errors, not as speed
}
CHANNEL_LAYERS = {"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}
