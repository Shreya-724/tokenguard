# Documentation

| Page | What it covers |
|---|---|
| [cost-model.md](cost-model.md) | Token estimates, model weights, reconciliation, budgets, near-limit alerts, streaming |
| [algorithms.md](algorithms.md) | Token bucket, fixed window, sliding window: comparison and which to use |
| [algorithm-benchmarks.md](algorithm-benchmarks.md) | Measured speed and memory per key for the three algorithms, with a chart |
| [live-rules.md](live-rules.md) | Changing limits while the server runs, and how changes spread |
| [metrics.md](metrics.md) | What is recorded, how it is stored, and how to query it |
| [dashboard-backend.md](dashboard-backend.md) | The staff-only REST API, sign-in, and the WebSocket feed |
| [dashboard.md](dashboard.md) | The React dashboard: panels, connection behaviour, look and feel |
| [demo-script.md](demo-script.md) | A 60-second demo script and how to record the GIF |
| [race-condition.md](race-condition.md) | The check-then-act race, reproduced and fixed with Lua |

Reproducible numbers: `python scripts/compare_algorithms.py`.
