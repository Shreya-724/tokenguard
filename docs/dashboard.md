# The dashboard (React)

A single dense screen for watching the limiter and changing it live.

```
dashboard/             Vite + React + Recharts, plain CSS, no other UI library
  src/lib/             logic with no React in it (tested with node --test)
    connection.js        the connection state machine
    backoff.js           0.5s, 1s, 2s, 4s, 8s, then 10s
    series.js            chart data, before/after maths
    rules.js             the rule editor's form logic
    api.js               REST calls, CSRF, errors
  src/hooks/ src/components/
  test/                72 tests, run with `npm test` (Node 20+, nothing to install)
```

## Run it

Backend (see docs/dashboard-backend.md for settings), in three terminals:

```
python demo/manage.py runserver          # Django over ASGI
python demo/manage.py tokenguard_feed    # pushes a snapshot every second
python scripts/load_demo.py              # traffic: four API keys, one hammers for 30 s
```

Create a staff user once: `python demo/manage.py createsuperuser`.

Frontend:

```
cd dashboard
npm install
npm run dev                              # http://localhost:5173
```

Open it, sign in with the staff user. The dev server proxies `/tokenguard` and
`/ws` to Django (`DJANGO_URL`, default http://localhost:8000), so the browser
sees one origin and the session cookie, CSRF token and WebSocket `Origin` all
work without CORS settings.

`npm test` runs the logic tests. `npm run build` writes `dist/`.

## What is on the screen

| Panel | What it shows |
|---|---|
| Status (top bar) | `CONNECTED`, `RECONNECTING #n next try in 3s [RETRY NOW]`, or `DISCONNECTED`; `STALE` if frames stop arriving while connected (is `tokenguard_feed` running?) |
| KPI strip | requests/s now and average, allowed, blocked, block rate, tokens |
| Traffic | allowed and blocked per second; 1M / 3M / 10M windows |
| Top consumers | heaviest keys by tokens; click one to watch its bucket |
| Most blocked | keys turned away most often (a ranking, not a per-request log: the server counts per key) |
| Rules traffic | requests and blocked share per rule |
| Bucket level | a key's remaining, used, time to full, algorithm; polls once a second |
| Rule editor | pick a rule, edit capacity, refill rate and algorithm, apply live or reset |

**Changing a limit.** Apply puts a dashed marker on the chart at the moment of
the change (`capacity 60→100`) and a `LIVE` marker when servers start using it
(`LIVE_RULES_TTL` later). The editor lists each change with the blocked share in
the 30 s before it and the 30 s after it goes live, so you see the effect.

## How the connection behaves

Three states, no others:

- `connected`: the socket is open.
- `reconnecting`: connecting, or waiting to retry. Delays double from 0.5 s to a
  10 s cap (0.5, 1, 2, 4, 8, 10, 10, ...), with no jitter, and reset as soon as a
  frame arrives. `RETRY NOW` skips the wait.
- `disconnected`: stopped, or refused for good because the session ended (sign in
  again; retrying cannot help).

A socket that stays open but goes silent (no data, no pong for 15 s) is declared
dead and replaced. The page pings every 5 s so a half-open connection is noticed.
If the first connect fails, the page asks the REST API whether you are still
signed in: Channels refuses a signed-out visitor with a plain 403, which looks
like a network error to the browser.

The chart keeps ten minutes of history in the browser and merges every snapshot
into it, so it does not blank out across a reconnect.

## Look and feel

Raw charcoal (`#09090b`, `#18181b`), hairline borders instead of shadows, square
corners everywhere, monospace type with tabular numerals so live values do not
make the layout jump. The chart uses straight (`linear`) lines, no animation, no
vertical gridlines, and draws BLOCKED last and more than twice as thick as
ALLOWED. It is plain CSS with custom properties (no Tailwind or UI kit).

## Limits

- Bucket gauge: rules with a budget show an error (the server cannot read them yet).
- History lives in the browser tab only; a reload starts from the server's last
  60 seconds.
- No pagination or search; it is built for a handful of rules and a short top list.
