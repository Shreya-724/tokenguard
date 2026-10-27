# The 60-second demo

What a recruiter should see in one minute: live traffic, a client hitting its
limit, a limit changed with no restart, and the effect on screen.

## Before you start (once)

Four terminals and one browser window.

```
docker compose up -d                         # Redis
python demo/manage.py runserver              # Django (ASGI)
python demo/manage.py tokenguard_feed        # pushes a snapshot every second
cd dashboard && npm run dev                  # http://localhost:5173
```

Then:

1. `python scripts/demo_check.py` and fix any `FAIL`. (A `warn` about no traffic is
   fine until the load starts.)
2. Open http://localhost:5173 in a window about 1280x720, sign in, and confirm the
   top bar says `CONNECTED  frame just now`.
3. In the rule editor, pick `demo_site.views.keyed`. It should read capacity 30,
   refill 2 and show no `[overridden]`. If an old change is left, press RESET.
4. Have a fifth terminal ready with this command, not started yet:

```
python scripts/load_demo.py --seconds 60 --phase-seconds 20
```

## The script

`load_demo.py` runs three 20-second phases: everyone calm, then `mallory` hammers
the API, then calm again. Start it, and follow the clock.

| Time | Do | Say |
|---|---|---|
| 0:00 | Start `load_demo.py`. Point at the chart and the top bar. | "This is tokenguard, a Redis-backed rate limiter for Django. That is live traffic, one sample a second over a WebSocket. Blue is allowed, red is blocked." |
| 0:12 | Click the `CONNECTED` status, then the top consumer row (a key). | "Every decision is recorded in one atomic Redis call, so this is per key and per rule, and it is the same for every server." The bucket gauge fills in. |
| 0:20 | Mallory starts. The red line jumps; the block rate turns red. | "Here one client starts hammering the API. Her bucket empties and the limiter starts returning 429s: that is the red line." |
| 0:25 | Click mallory in MOST BLOCKED. | "Her bucket is empty, and the gauge shows when it refills. Everyone else is unaffected." |
| 0:32 | In the rule editor set REFILL / S to `30`, press APPLY LIVE. A dashed marker appears. | "Now I change her limit while the server is running. No deploy, no restart. It is stored in Redis and every server picks it up within two seconds." |
| 0:36 | The `LIVE` marker appears; the red line drops. | "That is the moment the new rule went live, and the blocking stops." |
| 0:45 | Point at CHANGES: BEFORE / AFTER. | "The editor compares the blocked share before and after the change, so I can see what I did." |
| 0:52 | Press RESET. | "And one click puts it back to what the settings say." |
| 0:57 | (Optional) stop `runserver` with Ctrl+C. The bar goes `RECONNECTING #1 next try in...`. | "If the connection drops, it backs off 0.5, 1, 2, 4, 8 seconds and then keeps trying every 10, and recovers by itself." |

If you only have 45 seconds, drop the 0:12 and 0:52 rows.

## Recording the GIF (Windows)

Option A, [ScreenToGif](https://www.screentogif.com/): Recorder, drag the frame
over the browser window (1280x720 is ideal), 15 fps, press Record, then run the
script. Stop, trim the first and last second in the Editor, and Save as GIF
(Gifski encoder, quality about 80). Keep it under 10 MB.

Option B, Xbox Game Bar (Win+Alt+R) to make an MP4, then:

```
ffmpeg -i demo.mp4 -vf "fps=12,scale=960:-1:flags=lanczos" -loop 0 docs/demo.gif
```

Tips: use a dark OS theme, hide bookmarks and other tabs, zoom the browser to 100%
(or 110% for readability), and do one practice run first so the 0:32 edit is smooth.

Save the file as `docs/demo.gif`, then remove the comment markers around the image
line near the top of `README.md`.

## If something looks wrong

| Symptom | Likely cause |
|---|---|
| `STALE no data` in the bar | `tokenguard_feed` is not running |
| `RECONNECTING` forever at the start | Django is not running, or not on port 8000 |
| Login form after you were signed in | the session expired: sign in again |
| No blocked line during the hammer phase | an old override is raising the limit: press RESET |
| Empty chart with `AWAITING FIRST FRAME` | `"METRICS": True` is missing from settings |
