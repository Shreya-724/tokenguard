"""End-to-end check against a running demo server (real HTTP, real Redis).

Usage: python scripts/e2e_http.py http://localhost:8000
The /login/ rule allows a burst of 5, then must answer 429.
"""

import json
import sys
import urllib.error
import urllib.request

base = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8000"


def get(path):
    try:
        with urllib.request.urlopen(base + path) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


codes = []
for i in range(7):
    status, headers, body = get("/login/")
    codes.append(status)
    print(i + 1, status, headers.get("X-RateLimit-Remaining"), headers.get("Retry-After"))

assert codes[:5] == [200] * 5, codes
assert codes[5:] == [429, 429], codes
assert int(headers["Retry-After"]) >= 1
assert json.loads(body)["error"] == "rate_limited"
status, headers, _ = get("/health/")
assert status == 200 and "X-RateLimit-Limit" not in headers  # exempt
print("E2E OK")
