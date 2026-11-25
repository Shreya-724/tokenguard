# Running the demo and the tests

The dashboard and its traffic generator are covered in [docs/dashboard.md](dashboard.md)
and [docs/demo-script.md](demo-script.md) (a 60-second walkthrough).

```bash
git clone https://github.com/Shreya-724/tokenguard && cd tokenguard
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d

python demo/manage.py runserver        # then try the curl above
pytest                                 # unit, shared, concurrency and Django tests
python scripts/latency.py              # per-call latency (localhost Redis)
python scripts/demo_llm.py             # the LLM demo (server must be running)
python scripts/compare_algorithms.py   # edge burst, memory and speed per algorithm
python scripts/demo_live_rules.py      # change a limit live (needs LIVE_RULES on)
python scripts/tokenguard_rules.py list    # inspect or change live rules
python scripts/tokenguard_stats.py top     # who is using the most right now
python scripts/load_demo.py                # traffic for the dashboard
python scripts/demo_check.py               # is everything up for a demo?
python demo/manage.py tokenguard_feed      # feeds the dashboard (WebSocket)
(cd dashboard && npm install && npm run dev && npm test)   # the React dashboard
```

Demo endpoints: `/api/ping/` (default rule), `/api/report/` (decorator, costs 5
tokens), `/login/` (route rule, fail-closed), `/api/chat/` (DRF view),
`/health/` (exempt), `/api/config/` (shows the active settings), `/api/fixed/` (a
fixed-window view), `/api/keyed/` (one bucket per `X-API-Key`), `/api/summary/` (class-based view), and the mock LLM API: `/api/llm/chat/`, `/api/complete/`, `/api/complete-manual/`, `/api/budgeted/`.
