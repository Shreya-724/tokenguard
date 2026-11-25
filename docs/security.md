# Security and failure behaviour

What happens when Redis fails, how client IPs are read, and what a hostile client
can try. For the short version, see the [README](../README.md).

## Fail-open vs fail-closed

If Redis is unreachable (timeouts are short, `REDIS_TIMEOUT`):

- **`open`**: the request goes through and a warning is logged. Choose this for
  public reads, where availability matters more than a few extra requests.
- **`closed`**: the request gets `503`. Choose this where abuse is costly: login
  endpoints (brute force), expensive or paid operations.

Set a global default with `FAIL_MODE` and override it per rule or decorator with
`fail_mode=`.

## Client IP and `X-Forwarded-For`

`X-Forwarded-For` is a normal header, so any client can send a fake one. If it were
trusted blindly, an attacker could rotate fake IPs and never be limited.
tokenguard **ignores it** unless the direct peer is listed in `TRUSTED_PROXIES`. It
then reads the header from the right and takes the first address that is not one of
your own proxies.

## Security considerations

What a hostile client can try, what tokenguard does about it, and what is left to you.
`python benchmarks/key_flood.py --yes` demonstrates the memory points below on your
own Redis.

| Attack | What tokenguard does | What you must do |
|---|---|---|
| **Fake `X-Forwarded-For`** to look like a new client on every request | Ignores the header unless the direct peer is in `TRUSTED_PROXIES`; then reads it from the right, so entries a client adds on the left are never believed. Garbage in the header means the whole header is ignored. | List only your own proxies or load balancers, as narrowly as you can (never `0.0.0.0/0`). Make sure your proxy appends to the header rather than passing a client's through. |
| **Rotating identities** (a made-up `X-API-Key` on every request, a new IP each time) | Each new identity gets its own full bucket, so a limiter keyed by an unverified value cannot stop this. `api_key_if(check)` limits unknown keys by IP instead. | Key by something you have verified (`user`, or `api_key_if` with a real lookup). Put an IP-keyed rule in front of anything that is keyed by a client-supplied value. |
| **Huge identities** to bloat Redis keys | `MAX_KEY_LENGTH` (default 128): a longer identity becomes `h:` plus 32 hex characters of its SHA-256. The same long value still lands in the same bucket. API keys are always stored hashed. | Nothing, unless you need a different limit. |
| **A flood of one-off callers** to fill Redis | Every key has a TTL (a token bucket's lives twice the time it takes to refill from empty; a window's, one window plus a second; metrics, `METRICS_RETENTION` plus two minutes). `scripts/tokenguard_audit.py` reports keys that never expire. About 220 bytes per one-off caller on the token bucket (measured). | Set `maxmemory` and `maxmemory-policy volatile-lru` on Redis (the compose file does). Prefer the token bucket or fixed window: a sliding window stores one entry per request, 1.3 MB per key at a limit of 10,000. |
| **Budgets keyed by an unverified value** | Budget keys live 40 days (daily) and 400 days (monthly), so a flood of made-up owners is kept that long. | Only budget verified identities (`budget_key="user"`). |
| **Redis full, down or read-only** | A timeout, a dead connection, `OOM` (full with `noeviction`), `READONLY`, `BUSY` and `LOADING` all count as "Redis unavailable", and `FAIL_MODE` decides: `open` lets the request through, `closed` answers 503. Anything else (a script error, a wrong key type) still raises, so a bug is not hidden as an outage. | Choose `closed` for rules that guard against abuse (logins) and `open` where an outage should not take your API down. Know that with `volatile-lru`, an evicted caller's bucket starts full again. |
| **Reading or changing limits** | The rules API and dashboard are staff-only (session login with CSRF, or Basic auth), and the login endpoint is itself rate limited. | Anyone who can write to Redis can change limits and read keys: do not expose Redis (the compose file publishes 6379 for local development only), use a password and `rediss://` in production. Change the demo password `admin`/`admin`. |

Two sizing numbers, both measured on the author's machine (see
[docs/algorithm-benchmarks.md](algorithm-benchmarks.md)): a token-bucket or
fixed-window key is about 120 bytes of data, and 1 million distinct active callers
need a few hundred MB of Redis. If you key by IP behind a proxy and forget
`TRUSTED_PROXIES`, everyone shares the proxy's address and one bucket.
