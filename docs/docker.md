# Running with Docker

```bash
docker compose up --build
```

Four containers start:

| Service | Port | What it is |
|---|---|---|
| `redis` | 6379 | Redis 7, capped at 256 MB with `volatile-lru` eviction, data kept in a volume |
| `web` | 8000 | the demo Django site, served by daphne (HTTP and the WebSocket) |
| `feed` | none | runs `manage.py tokenguard_feed`: one stats snapshot per second for the live feed |
| `dashboard` | 8080 | the React dashboard, built once and served by nginx |

nginx passes `/tokenguard/` (the staff API) and `/ws/` (the live feed) to `web`, so
the browser sees a single origin and sessions, CSRF and the WebSocket all work.
`web` waits for Redis to be healthy, and `dashboard` waits for `web`.

Sign in at http://localhost:8080 as `admin` / `admin`. **That password is public**:
it is only for the demo and is set in `docker-compose.yml`.

Only Redis, to run the code from your own virtualenv: `docker compose up -d redis`.

## Make it show something

```bash
python scripts/load_demo.py          # from your venv; sends traffic to localhost:8000
python scripts/demo_check.py         # checks Redis, the server, the session endpoint
```

## When it does not start

| Symptom | Likely cause |
|---|---|
| `web` is "unhealthy" | `docker compose logs web`. Often a settings error, or Redis not reachable at `redis://redis:6379/0`. |
| `DisallowedHost` in the logs | The demo settings only allow `localhost`/`127.0.0.1` while `DEBUG = True`. Browse via `localhost`, or set `ALLOWED_HOSTS`. |
| Dashboard shows `STALE` | The socket is open but no stats frames arrive: the `feed` container is not running (`docker compose ps`, `docker compose logs feed`). |
| `web` logs `redis.exceptions.TimeoutError: Timeout reading from redis:6379` and the status flips between CONNECTED and RECONNECTING every few seconds | redis-py 8 with channels-redis (django/channels_redis#422). The repo pins `redis<8`; also set `"socket_timeout": 10` in `CHANNEL_LAYERS` (see dashboard-backend.md). |
| Dashboard loads but is `DISCONNECTED` | The WebSocket is being refused: check `docker compose logs web` for an Origin error, and that you use `localhost:8080`. |
| Sign-in says "Invalid" | The superuser is created on first start from the `DJANGO_SUPERUSER_*` variables. After changing them, `docker compose down -v` and up again. |
| Port already in use | Another Redis on 6379 (`docker ps`), or change the left side of `"6379:6379"`. |

## Things to know

- Behind nginx, Django sees nginx's address as the client. Every dashboard user
  therefore shares one IP, which matters for the login rate limit. In a real deployment
  put nginx's network in `TRUSTED_PROXIES` (see "Client IP" in the README) so the real
  client address is read from `X-Forwarded-For`.
- This is a demo setup: SQLite, `DEBUG = True`, a public password and a published
  Redis port. None of those belong in production.