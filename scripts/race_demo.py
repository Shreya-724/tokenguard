"""Fire 1000 requests at a capacity-100 bucket and count how many were allowed.

Usage: python scripts/race_demo.py --impl naive --mode threads
"""

import argparse
import sys
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor

sys.path.insert(0, "tests")
from _workers import build, run_batch  # noqa: E402

CAPACITY, TOTAL, RATE = 100, 1000, 0.0001


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--impl", choices=["naive", "lua"], required=True)
    ap.add_argument("--mode", choices=["threads", "processes"], default="threads")
    ap.add_argument("--url", default="redis://localhost:6379/0")
    args = ap.parse_args()

    key = f"race:{uuid.uuid4().hex}"
    if args.mode == "threads":
        bucket = build(args.impl, args.url, key, CAPACITY, RATE)
        with ThreadPoolExecutor(max_workers=50) as pool:
            allowed = sum(pool.map(lambda _: bucket.allow().allowed, range(TOTAL)))
    else:
        jobs = [(args.impl, args.url, key, CAPACITY, RATE, TOTAL // 8)] * 8
        with ProcessPoolExecutor(max_workers=8) as pool:
            allowed = sum(pool.map(run_batch, jobs))

    build(args.impl, args.url, key, CAPACITY, RATE)._r.delete(key)
    print(
        f"impl={args.impl} mode={args.mode} capacity={CAPACITY} "
        f"requests={TOTAL} allowed={allowed} over_limit_by={allowed - CAPACITY}"
    )


if __name__ == "__main__":
    main()