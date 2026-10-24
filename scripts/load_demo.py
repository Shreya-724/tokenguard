"""Generate traffic so the dashboard has something to show.

    python scripts/load_demo.py                      # 90 seconds, against :8000
    python scripts/load_demo.py --seconds 300 --base http://localhost:8000

Four simulated API keys call /api/keyed/ (30 burst, 2 per second each):
alice and bob stay under the limit, carol is busy, and mallory is quiet for a
while, then hammers the endpoint for 30 seconds and goes quiet again. Watch
the blocked line jump when she starts, then change the limit in the rule editor
and watch it move. Standard library only; Ctrl+C stops it.
"""

import argparse
import random
import threading
import time
import urllib.error
import urllib.request

# name -> requests per second in each 30-second phase (quiet, hammer, quiet)
CLIENTS = {
    "alice": (1.5, 1.5, 1.5),
    "bob": (0.5, 0.5, 0.5),
    "carol": (2.5, 2.5, 2.5),
    "mallory": (0.5, 25.0, 0.5),
}
PHASE_SECONDS = 30
counts = {"ok": 0, "blocked": 0, "error": 0}
lock = threading.Lock()


def call(base: str, key: str) -> None:
    request = urllib.request.Request(f"{base}/api/keyed/", headers={"X-API-Key": key})
    try:
        with urllib.request.urlopen(request, timeout=5):
            outcome = "ok"
    except urllib.error.HTTPError as exc:
        outcome = "blocked" if exc.code == 429 else "error"
    except OSError:
        outcome = "error"
    with lock:
        counts[outcome] += 1


def client(base: str, name: str, started: float, until: float) -> None:
    rates = CLIENTS[name]
    while time.time() < until:
        phase = int((time.time() - started) // PHASE_SECONDS) % len(rates)
        call(base, name)
        time.sleep(random.expovariate(rates[phase]))  # random gaps, like real users


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--seconds", type=int, default=90)
    args = parser.parse_args()
    started = time.time()
    until = started + args.seconds
    threads = [
        threading.Thread(
            target=client, args=(args.base, n, started, until), daemon=True
        )
        for n in CLIENTS
    ]
    for t in threads:
        t.start()
    try:
        while time.time() < until:
            time.sleep(5)
            with lock:
                print(
                    f"{int(time.time() - started):>4}s  ok={counts['ok']} "
                    f"blocked={counts['blocked']} errors={counts['error']}"
                )
    except KeyboardInterrupt:
        pass
    if counts["error"] and not counts["ok"]:
        print("every request failed: is the server running at", args.base, "?")


if __name__ == "__main__":
    main()
