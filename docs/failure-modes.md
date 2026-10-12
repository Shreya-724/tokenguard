# What happens when Redis is unreachable

tokenguard has two policies, set globally with `FAIL_MODE` and overridable per
rule or decorator with `fail_mode=`.

| Mode | Behavior | Choose it for |
|------|----------|---------------|
| `open` | The request is allowed, a warning is logged, and no rate-limit headers are sent | Public reads and anything where availability matters more than strict limits |
| `closed` | The request gets `503 {"error": "rate_limiter_unavailable"}` | Login and password reset (brute force), paid or expensive operations |

Redis calls time out after `REDIS_TIMEOUT` seconds (default 0.25), so a dead or
frozen Redis slows each request by at most that much instead of hanging the site.

Known limitation: there is no circuit breaker, so while Redis is down every request
still waits for the connection attempt or timeout. A frozen Redis costs up to
`REDIS_TIMEOUT` per request.